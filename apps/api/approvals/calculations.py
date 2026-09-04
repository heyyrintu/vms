from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal

from core.models import TDSPolicy

MONEY = Decimal("0.01")


def money(value):
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class AdvanceBreakdown:
    freight_rate: Decimal
    advance_percent: Decimal
    freight_advance_gross: Decimal
    remaining_freight_balance: Decimal
    advance_eligible_charges: Decimal
    advance_stage_deductions: Decimal
    gross_requested: Decimal
    tds_policy: str
    tds_rate: Decimal
    tds_base: Decimal
    previous_tds: Decimal
    tds_this_payment: Decimal
    net_requested: Decimal

    def as_dict(self):
        return {key: str(value) if isinstance(value, Decimal) else value for key, value in asdict(self).items()}


def calculate_advance(
    *,
    freight_rate,
    advance_percent=Decimal("90.00"),
    advance_eligible_charges=Decimal("0"),
    advance_stage_deductions=Decimal("0"),
    tds_rate=Decimal("1.00"),
    tds_policy=TDSPolicy.PER_PAYMENT_TAXABLE_AMOUNT,
    current_taxable_amount=None,
    cumulative_taxable_base=None,
    previous_tds=Decimal("0"),
    manual_tds=None,
    manual_tds_base=None,
    manual_reason="",
):
    freight_rate = money(freight_rate)
    advance_percent = Decimal(advance_percent)
    charges = money(advance_eligible_charges)
    deductions = money(advance_stage_deductions)
    tds_rate = Decimal(tds_rate)
    previous_tds = money(previous_tds)
    if min(freight_rate, charges, deductions, tds_rate, advance_percent, previous_tds) < 0:
        raise ValueError("Financial inputs cannot be negative")
    if advance_percent > 100:
        raise ValueError("Advance percent cannot exceed 100")

    freight_advance = money(freight_rate * advance_percent / Decimal("100"))
    gross = money(freight_advance + charges - deductions)
    if gross < 0:
        raise ValueError("Gross requested cannot be negative")
    current_taxable = money(gross if current_taxable_amount is None else current_taxable_amount)

    if tds_policy == TDSPolicy.PER_PAYMENT_TAXABLE_AMOUNT:
        tds_base = current_taxable
        tds = money(tds_base * tds_rate / Decimal("100"))
    elif tds_policy == TDSPolicy.FULL_FREIGHT_AT_FIRST_ADVANCE:
        tds_base = freight_rate if previous_tds == 0 else Decimal("0.00")
        tds = money(tds_base * tds_rate / Decimal("100"))
    elif tds_policy == TDSPolicy.CUMULATIVE_TRIP_LIABILITY:
        tds_base = money(cumulative_taxable_base if cumulative_taxable_base is not None else freight_rate)
        tds_target = money(tds_base * tds_rate / Decimal("100"))
        tds = max(Decimal("0.00"), money(tds_target - previous_tds))
    elif tds_policy == TDSPolicy.MANUAL_WITH_APPROVAL:
        if manual_tds is None or manual_tds_base is None or not manual_reason.strip():
            raise ValueError("Manual TDS requires amount, taxable base, and approval reason")
        tds = money(manual_tds)
        tds_base = money(manual_tds_base)
    else:
        raise ValueError("Unsupported TDS policy")

    if tds > gross:
        raise ValueError("TDS cannot exceed the gross request")
    return AdvanceBreakdown(
        freight_rate=freight_rate,
        advance_percent=advance_percent,
        freight_advance_gross=freight_advance,
        remaining_freight_balance=money(freight_rate - freight_advance),
        advance_eligible_charges=charges,
        advance_stage_deductions=deductions,
        gross_requested=gross,
        tds_policy=tds_policy,
        tds_rate=tds_rate,
        tds_base=money(tds_base),
        previous_tds=previous_tds,
        tds_this_payment=tds,
        net_requested=money(gross - tds),
    )


def calculate_final_settlement(*, final_freight, additive_charges=0, vendor_deductions=0, total_tds_required=0, total_cash_paid=0):
    gross_cost = money(Decimal(final_freight) + Decimal(additive_charges) - Decimal(vendor_deductions))
    net_payable = money(gross_cost - Decimal(total_tds_required))
    return {
        "final_vendor_gross_cost": gross_cost,
        "total_tds_required": money(total_tds_required),
        "net_vendor_payable_total": net_payable,
        "total_cash_paid": money(total_cash_paid),
        "remaining_cash_payable": money(net_payable - Decimal(total_cash_paid)),
    }


def calculate_profitability(*, client_billing_amount, final_vendor_gross_cost, internal_costs=0):
    billing = money(client_billing_amount)
    gross_profit = money(billing - Decimal(final_vendor_gross_cost) - Decimal(internal_costs))
    margin = Decimal("0.00") if billing == 0 else money(gross_profit / billing * Decimal("100"))
    return {"gross_profit": gross_profit, "margin_percent": margin}
