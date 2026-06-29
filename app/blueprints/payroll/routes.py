"""
Routes SSR du module Payroll (Paie).

Pages couvertes :
    GET  /payroll/                           → liste des bulletins (admin/rh)
    GET  /payroll/me                         → mes bulletins (employé connecté)
    GET/POST /payroll/generate               → génération d'un bulletin (admin/rh)
    GET  /payroll/<id>                       → détail d'un bulletin
    POST /payroll/<id>/validate              → passage draft → validated (admin/rh)
    POST /payroll/<id>/pay                   → passage validated → paid (admin/rh)
    POST /payroll/<id>/add-element           → ajout d'une ligne manuelle (admin/rh)
    GET  /payroll/<id>/print                 → vue impression (toutes parties autorisées)

Accès :
    - admin/rh : toutes les routes
    - employee/manager : uniquement /payroll/me et /payroll/<id> (leur bulletin)
"""
from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models.payroll import PaySlip
from app.services.payroll_service import (
    add_pay_element,
    generate_payslip,
    get_payslip,
    list_payslips,
    pay_payslip,
    validate_payslip,
)
from app.utils.decorators import require_role
from app.utils.exceptions import BusinessRuleError, ConflictError, NotFoundError
from . import bp
from .forms import AddPayElementForm, GeneratePaySlipForm, PaySlipActionForm, PaySlipFilterForm


# =============================================================================
# Helper
# =============================================================================

def _current_company_id() -> int | None:
    """Retourne la company_id de l'utilisateur connecté (fallback Company.get_default())."""
    if current_user.employee:
        return current_user.employee.company_id
    from app.models.organization import Company
    company = Company.get_default()
    return company.id if company else None


def _assert_payslip_access(payslip: PaySlip) -> None:
    """
    Vérifie que l'utilisateur courant a le droit de lire ce bulletin.
    Admin/RH voient tout. Employé/Manager voient uniquement les leurs.
    """
    role = current_user.role.name
    if role in ("admin", "rh"):
        return
    if current_user.employee and current_user.employee.id == payslip.employee_id:
        return
    abort(403, description="Accès refusé à ce bulletin de paie.")


# =============================================================================
# GET /payroll/ — liste des bulletins (admin/rh)
# =============================================================================

@bp.get("/")
@login_required
@require_role("admin", "rh")
def list_payslips_route():
    """Liste paginée des bulletins de paie, avec filtres."""
    company_id = _current_company_id()
    if company_id is None:
        abort(400, description="Aucune entreprise configurée.")

    filter_form = PaySlipFilterForm(request.args)
    filter_form.populate_employees(company_id)

    employee_id  = filter_form.employee_id.data or None
    period_year  = filter_form.period_year.data or None
    period_month = filter_form.period_month.data if filter_form.period_month.data and filter_form.period_month.data > 0 else None
    status       = filter_form.status.data or None

    payslips = list_payslips(
        company_id=company_id,
        employee_id=employee_id,
        period_year=period_year,
        period_month=period_month,
        status=status,
    )

    return render_template(
        "payroll/list.html",
        payslips=payslips,
        filter_form=filter_form,
    )


# =============================================================================
# GET /payroll/me — mes bulletins (employé connecté)
# =============================================================================

@bp.get("/me")
@login_required
def my_payslips():
    """Mes bulletins de paie personnels."""
    if not current_user.employee:
        abort(403, description="Aucun profil employé associé à ce compte.")

    payslips = list_payslips(employee_id=current_user.employee.id)

    return render_template(
        "payroll/list.html",
        payslips=payslips,
        filter_form=None,
        personal_view=True,
    )


# =============================================================================
# GET/POST /payroll/generate — génération d'un bulletin
# =============================================================================

@bp.route("/generate", methods=["GET", "POST"])
@login_required
@require_role("admin", "rh")
def generate():
    """Formulaire de génération d'un nouveau bulletin de paie."""
    company_id = _current_company_id()
    if company_id is None:
        abort(400, description="Aucune entreprise configurée.")

    form = GeneratePaySlipForm()
    form.populate_employees(company_id)

    if form.validate_on_submit():
        gross_override = form.gross_override.data if form.gross_override.data else None

        try:
            payslip = generate_payslip(
                employee_id=form.employee_id.data,
                period_year=form.period_year.data,
                period_month=form.period_month.data,
                gross_override=gross_override,
                notes=form.notes.data or None,
            )
        except NotFoundError as exc:
            flash(str(exc), "error")
        except ConflictError as exc:
            flash(str(exc), "warning")
        except BusinessRuleError as exc:
            flash(str(exc), "error")
        else:
            flash(
                f"Bulletin {payslip.period_label} généré pour "
                f"{payslip.employee.full_name} — net à payer : "
                f"{float(payslip.net_salary):,.2f} €.",
                "success",
            )
            return redirect(url_for("payroll.payslip_detail", payslip_id=payslip.id))

    return render_template("payroll/generate.html", form=form)


# =============================================================================
# GET /payroll/<id> — détail d'un bulletin
# =============================================================================

@bp.get("/<int:payslip_id>")
@login_required
def payslip_detail(payslip_id: int):
    """Détail d'un bulletin avec ses lignes de paie et les actions disponibles."""
    try:
        payslip = get_payslip(payslip_id)
    except NotFoundError:
        abort(404, description="Bulletin introuvable.")

    _assert_payslip_access(payslip)

    role = current_user.role.name
    can_manage = role in ("admin", "rh")

    validate_form  = PaySlipActionForm(prefix="validate")
    pay_form       = PaySlipActionForm(prefix="pay")
    add_elem_form  = AddPayElementForm(prefix="elem")

    return render_template(
        "payroll/detail.html",
        payslip=payslip,
        can_manage=can_manage,
        validate_form=validate_form,
        pay_form=pay_form,
        add_elem_form=add_elem_form,
        employee_contributions=[e for e in payslip.elements if not e.is_employer],
        employer_contributions=[e for e in payslip.elements if e.is_employer],
        bonuses=[e for e in payslip.elements if e.element_type == "bonus"],
        deductions=[e for e in payslip.elements if e.element_type == "deduction"],
    )


# =============================================================================
# POST /payroll/<id>/validate — passage draft → validated
# =============================================================================

@bp.post("/<int:payslip_id>/validate")
@login_required
@require_role("admin", "rh")
def validate_payslip_route(payslip_id: int):
    """Valide un bulletin (draft → validated)."""
    form = PaySlipActionForm(prefix="validate")
    if not form.validate_on_submit():
        abort(400)

    try:
        payslip = validate_payslip(payslip_id)
    except NotFoundError:
        abort(404)
    except BusinessRuleError as exc:
        flash(str(exc), "error")
    else:
        flash(
            f"Bulletin {payslip.period_label} de {payslip.employee.full_name} validé.",
            "success",
        )

    return redirect(url_for("payroll.payslip_detail", payslip_id=payslip_id))


# =============================================================================
# POST /payroll/<id>/pay — passage validated → paid
# =============================================================================

@bp.post("/<int:payslip_id>/pay")
@login_required
@require_role("admin", "rh")
def pay_payslip_route(payslip_id: int):
    """Marque un bulletin comme payé (validated → paid)."""
    form = PaySlipActionForm(prefix="pay")
    if not form.validate_on_submit():
        abort(400)

    payment_reference = request.form.get("payment_reference") or None

    try:
        payslip = pay_payslip(payslip_id, payment_reference=payment_reference)
    except NotFoundError:
        abort(404)
    except BusinessRuleError as exc:
        flash(str(exc), "error")
    else:
        flash(
            f"Bulletin {payslip.period_label} de {payslip.employee.full_name} marqué payé.",
            "success",
        )

    return redirect(url_for("payroll.payslip_detail", payslip_id=payslip_id))


# =============================================================================
# POST /payroll/<id>/add-element — ajout d'une ligne manuelle
# =============================================================================

@bp.post("/<int:payslip_id>/add-element")
@login_required
@require_role("admin", "rh")
def add_element_route(payslip_id: int):
    """Ajoute manuellement une ligne (prime, retenue) à un bulletin draft."""
    form = AddPayElementForm(prefix="elem")

    if not form.validate_on_submit():
        flash("Erreur de validation : " + "; ".join(
            f"{field}: {', '.join(errs)}"
            for field, errs in form.errors.items()
        ), "error")
        return redirect(url_for("payroll.payslip_detail", payslip_id=payslip_id))

    data = {
        "element_type": form.element_type.data,
        "label":        form.label.data,
        "amount":       form.amount.data,
        "is_employer":  form.is_employer.data,
        "rate":         form.rate.data if form.rate.data else None,
        "base_amount":  form.base_amount.data if form.base_amount.data else None,
    }

    try:
        element = add_pay_element(payslip_id, data)
    except NotFoundError:
        abort(404)
    except BusinessRuleError as exc:
        flash(str(exc), "error")
    else:
        flash(f"Ligne « {element.label} » ajoutée ({float(element.amount):,.2f} €).", "success")

    return redirect(url_for("payroll.payslip_detail", payslip_id=payslip_id))


# =============================================================================
# GET /payroll/<id>/print — vue impression
# =============================================================================

@bp.get("/<int:payslip_id>/print")
@login_required
def print_payslip(payslip_id: int):
    """Vue imprimable du bulletin (ouvre une page sans sidebar pour impression)."""
    try:
        payslip = get_payslip(payslip_id)
    except NotFoundError:
        abort(404, description="Bulletin introuvable.")

    _assert_payslip_access(payslip)

    return render_template(
        "payroll/print.html",
        payslip=payslip,
        employee_contributions=[e for e in payslip.elements if not e.is_employer],
        employer_contributions=[e for e in payslip.elements if e.is_employer],
        bonuses=[e for e in payslip.elements if e.element_type == "bonus"],
        deductions=[e for e in payslip.elements if e.element_type == "deduction"],
    )
