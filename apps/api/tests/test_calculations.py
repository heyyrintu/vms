from decimal import Decimal

import pytest

from approvals.calculations import (
    calculate_advance,
    calculate_final_settlement,
    calculate_profitability,
)
from core.models import TDSPolicy


def test_default_90_percent_advance_and_per_payment_tds():
    result = calculate_advance(
        freight_rate="50000",
        advance_percent="90",
        advance_eligible_charges="2500",
        current_taxable_amount="45000",
        tds_rate="1",
    )
    assert result.freight_advance_gross == Decimal("45000.00")
    assert result.remaining_freight_balance == Decimal("5000.00")
    assert result.gross_requested == Decimal("47500.00")
    assert result.tds_base == Decimal("45000.00")
    assert result.tds_this_payment == Decimal("450.00")
    assert result.net_requested == Decimal("47050.00")


@pytest.mark.parametrize(
    ("policy", "kwargs", "expected_base", "expected_tds"),
    [
        (TDSPolicy.PER_PAYMENT_TAXABLE_AMOUNT, {"current_taxable_amount": "45000"}, "45000.00", "450.00"),
        (TDSPolicy.FULL_FREIGHT_AT_FIRST_ADVANCE, {}, "50000.00", "500.00"),
        (
            TDSPolicy.CUMULATIVE_TRIP_LIABILITY,
            {"cumulative_taxable_base": "50000", "previous_tds": "200"},
            "50000.00",
            "300.00",
        ),
        (
            TDSPolicy.MANUAL_WITH_APPROVAL,
            {"manual_tds": "325", "manual_tds_base": "32500", "manual_reason": "Finance-approved exception"},
            "32500.00",
            "325.00",
        ),
    ],
)
def test_each_tds_mode(policy, kwargs, expected_base, expected_tds):
    result = calculate_advance(freight_rate="50000", tds_policy=policy, **kwargs)
    assert result.tds_base == Decimal(expected_base)
    assert result.tds_this_payment == Decimal(expected_tds)


def test_full_freight_tds_only_on_first_advance():
    result = calculate_advance(
        freight_rate="50000",
        tds_policy=TDSPolicy.FULL_FREIGHT_AT_FIRST_ADVANCE,
        previous_tds="500",
    )
    assert result.tds_base == Decimal("0.00")
    assert result.tds_this_payment == Decimal("0.00")


def test_manual_tds_requires_reason():
    with pytest.raises(ValueError, match="approval reason"):
        calculate_advance(
            freight_rate="50000",
            tds_policy=TDSPolicy.MANUAL_WITH_APPROVAL,
            manual_tds="100",
            manual_tds_base="10000",
        )


def test_settlement_and_profit_keep_tds_out_of_cost():
    settlement = calculate_final_settlement(
        final_freight="50000", additive_charges="2500", vendor_deductions="500", total_tds_required="500", total_cash_paid="45000"
    )
    assert settlement["final_vendor_gross_cost"] == Decimal("52000.00")
    assert settlement["remaining_cash_payable"] == Decimal("6500.00")
    profit = calculate_profitability(client_billing_amount="60000", final_vendor_gross_cost=settlement["final_vendor_gross_cost"])
    assert profit["gross_profit"] == Decimal("8000.00")


def test_negative_and_invalid_inputs_are_rejected():
    with pytest.raises(ValueError):
        calculate_advance(freight_rate="-1")
    with pytest.raises(ValueError):
        calculate_advance(freight_rate="100", advance_percent="110")
