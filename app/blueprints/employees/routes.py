"""
Routes SSR du module Employees.

Pages couvertes :
    GET  /employees/                       → liste (recherche, filtres, pagination)
    GET  /employees/new                      → formulaire de création
    POST /employees/new                       → traitement de la création
    GET  /employees/<id>                       → détail (infos + contrats)
    GET  /employees/<id>/edit                   → formulaire d'édition
    POST /employees/<id>/edit                    → traitement de l'édition
    POST /employees/<id>/contracts/new             → ajout d'un nouveau contrat
    GET  /employees/organigramme                    → vue arborescente par département

Toutes les routes nécessitent une session authentifiée et un rôle
admin/rh (gestion RH) ou manager (lecture sur son équipe) — appliqué
via @require_role. La logique métier est déléguée à employee_service.
"""
from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.contract import Contract
from app.models.department import Department
from app.models.employee import Employee
from app.services.employee_service import (
    create_employee,
    delete_employee,
    get_employee,
    list_employees,
    update_employee,
)
from app.utils.decorators import require_role
from app.utils.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from . import bp
from .forms import ContractForm, EmployeeForm


def _current_company_id() -> int:
    """Retourne la company_id de l'utilisateur connecté.

    Priorité :
    1. Fiche employé liée au compte (cas normal : employé / manager / RH).
    2. Première entreprise disponible en base (cas admin sans fiche employé).
    """
    if current_user.employee:
        return current_user.employee.company_id

    from app.models.organization import Company
    company = Company.get_default()
    if company is None:
        abort(400, description="Aucune entreprise configurée. Créez-en une d'abord.")
    return company.id


# =============================================================================
# GET /employees/ — liste
# =============================================================================

@bp.get("/")
@login_required
@require_role("admin", "rh", "manager")
def list_employees_route():
    """Liste paginée des employés, avec recherche et filtres."""
    company_id = _current_company_id()

    status_param = request.args.get("status") or None
    search_param = request.args.get("search") or None

    result = list_employees(
    company_id=company_id,
    department_id=request.args.get("department_id", type=int),
    status=status_param,
    search=search_param,
    page=request.args.get("page", type=int),
)

    departments = db.session.execute(
        Department.active_in_company(company_id)
    ).scalars().all()

    return render_template(
        "employees/list.html",
        employees=result.items,
        pagination=result,
        departments=departments,
        search=request.args.get("search", ""),
        status_filter=request.args.get("status", ""),
        department_filter=request.args.get("department_id", type=int),
        statuses=Employee.STATUSES,
    )


# =============================================================================
# GET/POST /employees/new — création
# =============================================================================

@bp.route("/new", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def new_employee():
    """Formulaire de création d'un nouvel employé."""
    company_id = _current_company_id()

    form = EmployeeForm()
    form.populate_choices(company_id)

    if form.validate_on_submit():
        payload = {
            "company_id": company_id,
            "first_name": form.first_name.data,
            "last_name": form.last_name.data,
            "gender": form.gender.data or None,
            "birth_date": form.birth_date.data,
            "personal_email": form.personal_email.data or None,
            "personal_phone": form.personal_phone.data or None,
            "professional_phone": form.professional_phone.data or None,
            "address_line1": form.address_line1.data or None,
            "city": form.city.data or None,
            "postal_code": form.postal_code.data or None,
            "department_id": form.department_id.data or None,
            "position_id": form.position_id.data or None,
            "site_id": form.site_id.data or None,
            "manager_id": form.manager_id.data or None,
            "employee_number": form.employee_number.data or None,
            "hire_date": form.hire_date.data,
            "probation_end_date": form.probation_end_date.data,
            "status": form.status.data,
            "notes": form.notes.data or None,
            "national_id_number": form.national_id_number.data or None,
            "annual_gross_salary": float(form.annual_gross_salary.data) if form.annual_gross_salary.data is not None else None,
            "iban": form.iban.data or None,
            "bic": form.bic.data or None,
        }

        try:
            employee = create_employee(payload, created_by_id=current_user.id)
        except (NotFoundError, ConflictError, ValidationError) as exc:
            flash(str(exc), "error")
        else:
            flash(f"Employé {employee.full_name} créé avec succès.", "success")
            return redirect(url_for("employees.detail", employee_id=employee.id))

    return render_template("employees/form.html", form=form, employee=None)


# =============================================================================
# GET /employees/<id> — détail
# =============================================================================

@bp.get("/<int:employee_id>")
@login_required
@require_role("admin", "rh", "manager")
def detail(employee_id: int):
    """Détail d'un employé : infos personnelles, professionnelles, contrats."""
    try:
        employee = get_employee(employee_id)
    except NotFoundError:
        abort(404, description="Employé introuvable.")

    contracts = db.session.execute(
        Contract.history_for_employee(employee_id)
    ).scalars().all()

    contract_form = ContractForm()
    contract_form.populate_contract_types(employee.company_id)

    return render_template(
        "employees/detail.html",
        employee=employee,
        contracts=contracts,
        contract_form=contract_form,
    )


# =============================================================================
# GET/POST /employees/<id>/edit — édition
# =============================================================================

@bp.route("/<int:employee_id>/edit", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def edit_employee(employee_id: int):
    """Formulaire d'édition d'un employé existant."""
    try:
        employee = get_employee(employee_id)
    except NotFoundError:
        abort(404, description="Employé introuvable.")

    form = EmployeeForm(obj=employee) if request.method == "GET" else EmployeeForm()
    form.populate_choices(employee.company_id, exclude_employee_id=employee_id)

    if request.method == "GET":
        # Pré-remplissage manuel (EmployeeForm n'utilise pas obj= nativement sans WTForms-Alchemy)
        form.first_name.data = employee.first_name
        form.last_name.data = employee.last_name
        form.gender.data = employee.gender or ""
        form.birth_date.data = employee.birth_date
        form.personal_email.data = employee.personal_email
        form.personal_phone.data = employee.personal_phone
        form.professional_phone.data = employee.professional_phone
        form.address_line1.data = employee.address_line1
        form.city.data = employee.city
        form.postal_code.data = employee.postal_code
        form.department_id.data = employee.department_id or 0
        form.position_id.data = employee.position_id or 0
        form.site_id.data = employee.site_id or 0
        form.manager_id.data = employee.manager_id or 0
        form.employee_number.data = employee.employee_number
        form.hire_date.data = employee.hire_date
        form.probation_end_date.data = employee.probation_end_date
        form.status.data = employee.status
        form.notes.data = employee.notes
        form.national_id_number.data = employee.national_id_number
        form.annual_gross_salary.data = employee.annual_gross_salary
        form.iban.data = employee.iban
        form.bic.data = employee.bic

    if form.validate_on_submit():
        payload = {
            "first_name": form.first_name.data,
            "last_name": form.last_name.data,
            "gender": form.gender.data or None,
            "birth_date": form.birth_date.data,
            "personal_email": form.personal_email.data or None,
            "personal_phone": form.personal_phone.data or None,
            "professional_phone": form.professional_phone.data or None,
            "address_line1": form.address_line1.data or None,
            "city": form.city.data or None,
            "postal_code": form.postal_code.data or None,
            "department_id": form.department_id.data or None,
            "position_id": form.position_id.data or None,
            "site_id": form.site_id.data or None,
            "manager_id": form.manager_id.data or None,
            "employee_number": form.employee_number.data or None,
            "hire_date": form.hire_date.data,
            "probation_end_date": form.probation_end_date.data,
            "status": form.status.data,
            "notes": form.notes.data or None,
            "national_id_number": form.national_id_number.data or None,
            "annual_gross_salary": float(form.annual_gross_salary.data) if form.annual_gross_salary.data is not None else None,
            "iban": form.iban.data or None,
            "bic": form.bic.data or None,
        }

        try:
            update_employee(employee_id, payload, updated_by_id=current_user.id)
        except (NotFoundError, ConflictError, BusinessRuleError, ValidationError) as exc:
            flash(str(exc), "error")
        else:
            flash("Employé mis à jour avec succès.", "success")
            return redirect(url_for("employees.detail", employee_id=employee_id))

    return render_template("employees/form.html", form=form, employee=employee)


# =============================================================================
# POST /employees/<id>/contracts/new — nouveau contrat
# =============================================================================

@bp.post("/<int:employee_id>/contracts/new")
@login_required
@require_role("admin", "rh")
def new_contract(employee_id: int):
    """Ajoute un nouveau contrat de travail à un employé."""
    try:
        employee = get_employee(employee_id)
    except NotFoundError:
        abort(404, description="Employé introuvable.")

    form = ContractForm()
    form.populate_contract_types(employee.company_id)

    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for err in errors:
                flash(f"{field} : {err}", "error")
        return redirect(url_for("employees.detail", employee_id=employee_id))

    if form.is_current.data:
        # Désactive l'ancien contrat courant avant d'en créer un nouveau
        current = Contract.get_current(employee_id)
        if current is not None:
            current.is_current = False
            db.session.add(current)

    contract = Contract(
        employee_id=employee_id,
        contract_type_id=form.contract_type_id.data,
        start_date=form.start_date.data,
        end_date=form.end_date.data,
        trial_end_date=form.trial_end_date.data,
        gross_salary=form.gross_salary.data,
        weekly_hours=form.weekly_hours.data,
        is_current=form.is_current.data,
        notes=form.notes.data or None,
    )
    db.session.add(contract)
    db.session.commit()

    flash("Contrat créé avec succès.", "success")
    return redirect(url_for("employees.detail", employee_id=employee_id))


# =============================================================================
# GET /employees/organigramme — vue arborescente
# =============================================================================

@bp.get("/organigramme")
@login_required
@require_role("admin", "rh", "manager")
def organigramme():
    """Vue arborescente de l'organisation par département."""
    company_id = _current_company_id()

    root_departments = db.session.execute(
        Department.root_departments(company_id)
    ).scalars().all()

    return render_template(
        "employees/organigramme.html",
        departments=root_departments,
    )


# =============================================================================
# POST /employees/<id>/terminate — départ (suppression logique)
# =============================================================================

@bp.post("/<int:employee_id>/terminate")
@login_required
@require_role("admin", "rh")
def terminate_employee(employee_id: int):
    """Marque un employé comme parti (suppression logique, jamais physique)."""
    from datetime import date as _date

    raw_date = request.form.get("termination_date")
    termination_date = _date.fromisoformat(raw_date) if raw_date else None
    reason = request.form.get("termination_reason") or None

    try:
        delete_employee(
            employee_id,
            termination_date=termination_date,
            termination_reason=reason,
            deleted_by_id=current_user.id,
        )
    except NotFoundError:
        abort(404, description="Employé introuvable.")
    except BusinessRuleError as exc:
        flash(str(exc), "error")
        return redirect(url_for("employees.detail", employee_id=employee_id))

    flash("Le départ de l'employé a été enregistré.", "info")
    return redirect(url_for("employees.list_employees_route"))