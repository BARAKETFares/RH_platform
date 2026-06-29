"""
Routes SSR du module Admin.

Pages couvertes :
    GET  /admin/                              → redirige vers la liste des utilisateurs

    GET  /admin/users/                        → liste des comptes (search, filtre rôle, pagination)
    GET  /admin/users/new                      → formulaire de création d'un compte
    POST /admin/users/new                       → traitement de la création
    GET  /admin/users/<uuid>/edit               → formulaire d'édition d'un compte
    POST /admin/users/<uuid>/edit                → traitement de l'édition

    GET  /admin/roles/                            → liste des rôles
    GET  /admin/roles/<id>/edit                    → formulaire d'édition d'un rôle
    POST /admin/roles/<id>/edit                     → traitement de l'édition

    GET  /admin/audit/                               → journal d'audit (filtres + pagination)

Toutes les routes exigent le rôle « admin ».
"""
from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.audit import AuditLog
from app.models.employee import Employee
from app.models.role import Permission, Role, RolePermission
from app.models.user import User
from app.utils.decorators import require_role
from app.utils.pagination import paginate
from . import bp
from .forms import (
    AuditLogFilterForm,
    ContractTypeForm,
    DepartmentForm,
    LeaveTypeForm,
    PositionForm,
    RoleEditForm,
    SiteForm,
    UserCreateForm,
    UserEditForm,
)


# =============================================================================
# Helpers
# =============================================================================

def _admin_company_id() -> int:
    """Retourne la company de l'admin connecté, ou la première company disponible."""
    from app.models.organization import Company
    if current_user.employee:
        return current_user.employee.company_id
    company = Company.get_default()
    if company is None:
        abort(400, description="Aucune entreprise configurée dans la base.")
    return company.id


def _get_user_or_404(uuid: str) -> User:
    user = User.get_by_uuid(uuid)
    if user is None:
        abort(404, description="Utilisateur introuvable.")
    return user


def _audit(action: str, entity_id: int | None = None, **extra) -> None:
    try:
        AuditLog.record(
            action=action,
            user_id=current_user.id,
            user_email=current_user.email,
            entity_type="users",
            entity_id=entity_id,
            extra_data=extra or None,
            ip_address=request.remote_addr,
        )
    except Exception:
        pass


# =============================================================================
# GET /admin/ — index
# =============================================================================

@bp.get("/")
@login_required
@require_role("admin")
def index():
    return redirect(url_for("admin.list_users"))


# =============================================================================
# GET /admin/users/ — liste des utilisateurs
# =============================================================================

@bp.get("/users/")
@login_required
@require_role("admin")
def list_users():
    """Liste paginée des comptes, avec recherche par e-mail et filtre par rôle."""
    search = request.args.get("search", "").strip()
    role_filter = request.args.get("role_id", type=int)

    query = db.select(User).order_by(User.created_at.desc())

    if search:
        query = query.where(User.email.ilike(f"%{search}%"))
    if role_filter:
        query = query.where(User.role_id == role_filter)

    result = paginate(query)
    roles = Role.all_ordered()

    return render_template(
        "admin/users.html",
        users=result.items,
        pagination=result,
        roles=roles,
        search=search,
        role_filter=role_filter,
    )


# =============================================================================
# GET /POST /admin/users/new — création d'un compte
# =============================================================================

@bp.route("/users/new", methods=["GET", "POST"])
@login_required
@require_role("admin")
def new_user():
    form = UserCreateForm()
    form.populate_roles()
    form.populate_employees()

    if form.validate_on_submit():
        if User.get_by_email(form.email.data):
            flash("Un compte avec cet e-mail existe déjà.", "error")
            return render_template("admin/user_form.html", form=form, user=None)

        user = User(
            email=form.email.data,
            role_id=form.role_id.data,
            is_active=form.is_active.data,
            force_password_change=form.force_password_change.data,
            preferred_language=form.preferred_language.data,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()

        # Lier à une fiche employé si sélectionnée
        emp_id = form.employee_id.data
        if emp_id:
            emp = db.session.get(Employee, emp_id)
            if emp and emp.user_id is None:
                emp.user_id = user.id

        _audit(AuditLog.ACTION_CREATE, entity_id=user.id, email=user.email)
        db.session.commit()

        flash(f"Compte « {user.email} » créé avec succès.", "success")
        return redirect(url_for("admin.list_users"))

    return render_template("admin/user_form.html", form=form, user=None)


# =============================================================================
# GET /POST /admin/users/<uuid>/edit — édition d'un compte
# =============================================================================

@bp.route("/users/<uuid>/edit", methods=["GET", "POST"])
@login_required
@require_role("admin")
def edit_user(uuid: str):
    user = _get_user_or_404(uuid)
    current_employee = user.employee
    current_emp_id = current_employee.id if current_employee else None

    form = UserEditForm(obj=user)
    form.populate_roles()
    form.populate_employees(current_emp_id)

    if form.validate_on_submit():
        old_email = user.email

        user.email = form.email.data
        user.role_id = form.role_id.data
        user.is_active = form.is_active.data
        user.is_email_verified = form.is_email_verified.data
        user.force_password_change = form.force_password_change.data

        if form.new_password.data:
            user.set_password(form.new_password.data)

        # Gérer la liaison / déliaison de la fiche employé
        new_emp_id = form.employee_id.data or 0
        if new_emp_id != (current_emp_id or 0):
            # Délier l'ancien employé
            if current_employee:
                current_employee.user_id = None
            # Lier le nouvel employé
            if new_emp_id:
                new_emp = db.session.get(Employee, new_emp_id)
                if new_emp:
                    new_emp.user_id = user.id

        _audit(AuditLog.ACTION_UPDATE, entity_id=user.id,
               old_email=old_email, new_email=user.email)
        db.session.commit()

        flash(f"Compte « {user.email} » mis à jour.", "success")
        return redirect(url_for("admin.list_users"))

    if request.method == "GET":
        form.is_active.data = user._is_active
        form.role_id.data = user.role_id
        form.employee_id.data = current_emp_id or 0

    return render_template("admin/user_form.html", form=form, user=user,
                           current_employee=current_employee)


# =============================================================================
# GET /admin/roles/ — liste des rôles
# =============================================================================

@bp.get("/roles/")
@login_required
@require_role("admin")
def list_roles():
    roles = Role.all_ordered()
    return render_template("admin/roles/list.html", roles=roles)


# =============================================================================
# GET /POST /admin/roles/<id>/edit — édition d'un rôle
# =============================================================================

@bp.route("/roles/<int:role_id>/edit", methods=["GET", "POST"])
@login_required
@require_role("admin")
def edit_role(role_id: int):
    role = Role.get_or_404(role_id)

    current_perm_ids = [rp.permission_id for rp in role.role_permissions]
    form = RoleEditForm(obj=role)
    form.populate_permissions()  # choices uniquement — data préservées du POST

    if form.validate_on_submit():
        role.label = form.label.data
        role.description = form.description.data

        # Synchronise les permissions : supprime les retirées, ajoute les nouvelles
        new_ids = set(form.permission_ids.data or [])
        old_ids = set(current_perm_ids)

        for rp in list(role.role_permissions):
            if rp.permission_id not in new_ids:
                db.session.delete(rp)

        existing_ids = {rp.permission_id for rp in role.role_permissions}
        for perm_id in new_ids - old_ids:
            if perm_id not in existing_ids:
                perm = db.session.get(Permission, perm_id)
                if perm:
                    role.role_permissions.append(
                        RolePermission(role_id=role.id, permission_id=perm.id)
                    )

        _audit(
            AuditLog.ACTION_PERMISSION_CHANGE,
            entity_id=role.id,
            entity_type_override="roles",
            added=list(new_ids - old_ids),
            removed=list(old_ids - new_ids),
        )
        db.session.commit()

        flash(f"Rôle « {role.name} » mis à jour.", "success")
        return redirect(url_for("admin.list_roles"))

    if request.method == "GET":
        form.permission_ids.data = current_perm_ids

    return render_template("admin/roles/form.html", form=form, role=role)


# =============================================================================
# GET /admin/audit/ — journal d'audit
# =============================================================================

# =============================================================================
# Départements
# =============================================================================

@bp.get("/departments/")
@login_required
@require_role("admin", "rh")
def list_departments():
    company_id = _admin_company_id()
    from app.models.department import Department
    depts = db.session.execute(
        db.select(Department)
        .where(Department.company_id == company_id)
        .order_by(Department.name)
    ).scalars().all()
    return render_template("admin/departments/list.html", departments=depts)


@bp.route("/departments/new", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def new_department():
    company_id = _admin_company_id()
    form = DepartmentForm()
    form.populate_parents(company_id)

    if form.validate_on_submit():
        from app.models.department import Department
        dept = Department(
            company_id=company_id,
            name=form.name.data,
            code=form.code.data.upper() if form.code.data else None,
            description=form.description.data or None,
            parent_id=form.parent_id.data or None,
            is_active=form.is_active.data,
        )
        db.session.add(dept)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Un département avec ce nom existe déjà.", "error")
            return render_template("admin/departments/form.html", form=form, department=None)
        flash(f"Département « {dept.name} » créé avec succès.", "success")
        return redirect(url_for("admin.list_departments"))

    return render_template("admin/departments/form.html", form=form, department=None)


@bp.route("/departments/<int:dept_id>/edit", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def edit_department(dept_id: int):
    from app.models.department import Department
    dept = db.session.get(Department, dept_id)
    if dept is None:
        abort(404, description="Département introuvable.")

    form = DepartmentForm()
    form.populate_parents(dept.company_id, exclude_id=dept_id)

    if request.method == "GET":
        form.name.data = dept.name
        form.code.data = dept.code
        form.description.data = dept.description
        form.parent_id.data = dept.parent_id or 0
        form.is_active.data = dept.is_active

    if form.validate_on_submit():
        dept.name = form.name.data
        dept.code = form.code.data.upper() if form.code.data else None
        dept.description = form.description.data or None
        dept.parent_id = form.parent_id.data or None
        dept.is_active = form.is_active.data
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Un département avec ce nom existe déjà.", "error")
            return render_template("admin/departments/form.html", form=form, department=dept)
        flash(f"Département « {dept.name} » mis à jour.", "success")
        return redirect(url_for("admin.list_departments"))

    return render_template("admin/departments/form.html", form=form, department=dept)


# =============================================================================
# Postes
# =============================================================================

@bp.get("/positions/")
@login_required
@require_role("admin", "rh")
def list_positions():
    company_id = _admin_company_id()
    from app.models.department import Department
    from app.models.position import Position
    positions = db.session.execute(
        db.select(Position)
        .join(Department, Position.department_id == Department.id)
        .where(Department.company_id == company_id)
        .order_by(Department.name, Position.title)
    ).scalars().all()
    return render_template("admin/positions/list.html", positions=positions)


@bp.route("/positions/new", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def new_position():
    company_id = _admin_company_id()
    form = PositionForm()
    form.populate_departments(company_id)

    if form.validate_on_submit():
        from app.models.position import Position
        pos = Position(
            department_id=form.department_id.data,
            title=form.title.data,
            level=form.level.data or None,
            description=form.description.data or None,
            min_salary=float(form.min_salary.data) if form.min_salary.data is not None else None,
            max_salary=float(form.max_salary.data) if form.max_salary.data is not None else None,
            is_active=form.is_active.data,
        )
        db.session.add(pos)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Un poste avec cet intitulé existe déjà dans ce département.", "error")
            return render_template("admin/positions/form.html", form=form, position=None)
        flash(f"Poste « {pos.title} » créé avec succès.", "success")
        return redirect(url_for("admin.list_positions"))

    return render_template("admin/positions/form.html", form=form, position=None)


@bp.route("/positions/<int:pos_id>/edit", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def edit_position(pos_id: int):
    from app.models.position import Position
    pos = db.session.get(Position, pos_id)
    if pos is None:
        abort(404, description="Poste introuvable.")

    from app.models.department import Department
    company_id = db.session.get(Department, pos.department_id).company_id
    form = PositionForm()
    form.populate_departments(company_id)

    if request.method == "GET":
        form.title.data = pos.title
        form.department_id.data = pos.department_id
        form.level.data = pos.level or ""
        form.description.data = pos.description
        form.min_salary.data = pos.min_salary
        form.max_salary.data = pos.max_salary
        form.is_active.data = pos.is_active

    if form.validate_on_submit():
        pos.title = form.title.data
        pos.department_id = form.department_id.data
        pos.level = form.level.data or None
        pos.description = form.description.data or None
        pos.min_salary = float(form.min_salary.data) if form.min_salary.data is not None else None
        pos.max_salary = float(form.max_salary.data) if form.max_salary.data is not None else None
        pos.is_active = form.is_active.data
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Un poste avec cet intitulé existe déjà dans ce département.", "error")
            return render_template("admin/positions/form.html", form=form, position=pos)
        flash(f"Poste « {pos.title} » mis à jour.", "success")
        return redirect(url_for("admin.list_positions"))

    return render_template("admin/positions/form.html", form=form, position=pos)


# =============================================================================
# Sites
# =============================================================================

@bp.get("/sites/")
@login_required
@require_role("admin", "rh")
def list_sites():
    company_id = _admin_company_id()
    from app.models.organization import Site
    sites = db.session.execute(
        db.select(Site)
        .where(Site.company_id == company_id)
        .order_by(Site.name)
    ).scalars().all()
    return render_template("admin/sites/list.html", sites=sites)


@bp.route("/sites/new", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def new_site():
    company_id = _admin_company_id()
    form = SiteForm()

    if form.validate_on_submit():
        from app.models.organization import Site
        site = Site(
            company_id=company_id,
            name=form.name.data,
            address=form.address.data or None,
            city=form.city.data or None,
            postal_code=form.postal_code.data or None,
            country=form.country.data or "FR",
            is_active=form.is_active.data,
        )
        db.session.add(site)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Un site avec ce nom existe déjà.", "error")
            return render_template("admin/sites/form.html", form=form, site=None)
        flash(f"Site « {site.name} » créé avec succès.", "success")
        return redirect(url_for("admin.list_sites"))

    return render_template("admin/sites/form.html", form=form, site=None)


@bp.route("/sites/<int:site_id>/edit", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def edit_site(site_id: int):
    from app.models.organization import Site
    site = db.session.get(Site, site_id)
    if site is None:
        abort(404, description="Site introuvable.")

    form = SiteForm()

    if request.method == "GET":
        form.name.data = site.name
        form.address.data = site.address
        form.city.data = site.city
        form.postal_code.data = site.postal_code
        form.country.data = site.country
        form.is_active.data = site.is_active

    if form.validate_on_submit():
        site.name = form.name.data
        site.address = form.address.data or None
        site.city = form.city.data or None
        site.postal_code = form.postal_code.data or None
        site.country = form.country.data or "FR"
        site.is_active = form.is_active.data
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Un site avec ce nom existe déjà.", "error")
            return render_template("admin/sites/form.html", form=form, site=site)
        flash(f"Site « {site.name} » mis à jour.", "success")
        return redirect(url_for("admin.list_sites"))

    return render_template("admin/sites/form.html", form=form, site=site)


# =============================================================================
# Types de contrats
# =============================================================================

@bp.get("/contract-types/")
@login_required
@require_role("admin", "rh")
def list_contract_types():
    company_id = _admin_company_id()
    from app.models.contract import ContractType
    types = db.session.execute(
        db.select(ContractType)
        .where(ContractType.company_id == company_id)
        .order_by(ContractType.name)
    ).scalars().all()
    return render_template("admin/contract_types/list.html", contract_types=types)


@bp.route("/contract-types/new", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def new_contract_type():
    company_id = _admin_company_id()
    form = ContractTypeForm()

    if form.validate_on_submit():
        from app.models.contract import ContractType
        ct = ContractType(
            company_id=company_id,
            name=form.name.data,
            duration_type=form.duration_type.data,
            paid_leave_days=float(form.paid_leave_days.data),
            rtt_days=float(form.rtt_days.data),
            notice_period_days=int(form.notice_period_days.data or 0),
            is_active=form.is_active.data,
        )
        db.session.add(ct)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Un type de contrat avec ce nom existe déjà.", "error")
            return render_template("admin/contract_types/form.html", form=form, contract_type=None)
        flash(f"Type de contrat « {ct.name} » créé avec succès.", "success")
        return redirect(url_for("admin.list_contract_types"))

    return render_template("admin/contract_types/form.html", form=form, contract_type=None)


@bp.route("/contract-types/<int:ct_id>/edit", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def edit_contract_type(ct_id: int):
    from app.models.contract import ContractType
    ct = db.session.get(ContractType, ct_id)
    if ct is None:
        abort(404, description="Type de contrat introuvable.")

    form = ContractTypeForm()

    if request.method == "GET":
        form.name.data = ct.name
        form.duration_type.data = ct.duration_type
        form.paid_leave_days.data = ct.paid_leave_days
        form.rtt_days.data = ct.rtt_days
        form.notice_period_days.data = ct.notice_period_days or 0
        form.is_active.data = ct.is_active

    if form.validate_on_submit():
        ct.name = form.name.data
        ct.duration_type = form.duration_type.data
        ct.paid_leave_days = float(form.paid_leave_days.data)
        ct.rtt_days = float(form.rtt_days.data)
        ct.notice_period_days = int(form.notice_period_days.data or 0)
        ct.is_active = form.is_active.data
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Un type de contrat avec ce nom existe déjà.", "error")
            return render_template("admin/contract_types/form.html", form=form, contract_type=ct)
        flash(f"Type de contrat « {ct.name} » mis à jour.", "success")
        return redirect(url_for("admin.list_contract_types"))

    return render_template("admin/contract_types/form.html", form=form, contract_type=ct)


# =============================================================================
# Types de congés
# =============================================================================

@bp.get("/leave-types/")
@login_required
@require_role("admin", "rh")
def list_leave_types():
    company_id = _admin_company_id()
    from app.models.leave_type import LeaveType
    leave_types = db.session.execute(
        db.select(LeaveType)
        .where(LeaveType.company_id == company_id)
        .order_by(LeaveType.name)
    ).scalars().all()
    return render_template("admin/leave_types/list.html", leave_types=leave_types)


@bp.route("/leave-types/new", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def new_leave_type():
    company_id = _admin_company_id()
    form = LeaveTypeForm()

    if form.validate_on_submit():
        from app.models.leave_type import LeaveType
        lt = LeaveType(
            company_id=company_id,
            name=form.name.data,
            code=form.code.data.upper(),
            color_hex=form.color_hex.data,
            description=form.description.data or None,
            min_advance_notice_days=form.min_advance_notice_days.data or 0,
            max_consecutive_days=form.max_consecutive_days.data or None,
            requires_justification=form.requires_justification.data,
            requires_document=form.requires_document.data,
            is_paid=form.is_paid.data,
            impacts_leave_balance=form.impacts_leave_balance.data,
            is_active=form.is_active.data,
        )
        db.session.add(lt)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Un type de congé avec ce nom ou ce code existe déjà.", "error")
            return render_template("admin/leave_types/form.html", form=form, leave_type=None)
        flash(f"Type de congé « {lt.name} » créé avec succès.", "success")
        return redirect(url_for("admin.list_leave_types"))

    return render_template("admin/leave_types/form.html", form=form, leave_type=None)


@bp.route("/leave-types/<int:lt_id>/edit", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def edit_leave_type(lt_id: int):
    from app.models.leave_type import LeaveType
    lt = db.session.get(LeaveType, lt_id)
    if lt is None:
        abort(404, description="Type de congé introuvable.")

    form = LeaveTypeForm()

    if request.method == "GET":
        form.name.data = lt.name
        form.code.data = lt.code
        form.color_hex.data = lt.color_hex
        form.description.data = lt.description
        form.min_advance_notice_days.data = lt.min_advance_notice_days
        form.max_consecutive_days.data = lt.max_consecutive_days or 0
        form.requires_justification.data = lt.requires_justification
        form.requires_document.data = lt.requires_document
        form.is_paid.data = lt.is_paid
        form.impacts_leave_balance.data = lt.impacts_leave_balance
        form.is_active.data = lt.is_active

    if form.validate_on_submit():
        lt.name = form.name.data
        lt.code = form.code.data.upper()
        lt.color_hex = form.color_hex.data
        lt.description = form.description.data or None
        lt.min_advance_notice_days = form.min_advance_notice_days.data or 0
        lt.max_consecutive_days = form.max_consecutive_days.data or None
        lt.requires_justification = form.requires_justification.data
        lt.requires_document = form.requires_document.data
        lt.is_paid = form.is_paid.data
        lt.impacts_leave_balance = form.impacts_leave_balance.data
        lt.is_active = form.is_active.data
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Un type de congé avec ce nom ou ce code existe déjà.", "error")
            return render_template("admin/leave_types/form.html", form=form, leave_type=lt)
        flash(f"Type de congé « {lt.name} » mis à jour.", "success")
        return redirect(url_for("admin.list_leave_types"))

    return render_template("admin/leave_types/form.html", form=form, leave_type=lt)


# =============================================================================
# GET /admin/audit/ — journal d'audit
# =============================================================================

@bp.get("/audit/")
@login_required
@require_role("admin")
def audit_log():
    """Journal d'audit paginé, filtrable par action, ressource, e-mail et date."""
    form = AuditLogFilterForm(request.args)

    query = db.select(AuditLog).order_by(AuditLog.created_at.desc())

    action_val = request.args.get("action", "").strip()
    entity_type_val = request.args.get("entity_type", "").strip()
    user_email_val = request.args.get("user_email", "").strip()
    date_from_val = form.date_from.data
    date_to_val = form.date_to.data

    if action_val:
        query = query.where(AuditLog.action == action_val)
    if entity_type_val:
        query = query.where(AuditLog.entity_type == entity_type_val)
    if user_email_val:
        query = query.where(AuditLog.user_email.ilike(f"%{user_email_val}%"))
    if date_from_val:
        query = query.where(AuditLog.created_at >= date_from_val)
    if date_to_val:
        from datetime import datetime, timezone, timedelta
        end_of_day = datetime.combine(date_to_val, datetime.max.time()).replace(tzinfo=timezone.utc)
        query = query.where(AuditLog.created_at <= end_of_day)

    result = paginate(query, per_page=50)

    return render_template(
        "admin/audit_log.html",
        logs=result.items,
        pagination=result,
        form=form,
    )
