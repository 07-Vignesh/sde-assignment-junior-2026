from decimal import Decimal
from pipeline.normalize import (
    norm_header, norm_phone, norm_date, norm_decimal, norm_enum,
)


def test_header():
    assert norm_header("Customer_Name ") == "customer name"
    assert norm_header("customer   name") == "customer name"
    assert norm_header("  POLICY__NO ") == "policy no"


def test_phone_valid_formats():
    good = [
        "+916463745499", "9932302346", "+91 79328 96340",
        "(+91) 8196106462", "06832582386", "91-81518-64492",
    ]
    for raw in good:
        assert norm_phone(raw).startswith("+91")
        assert len(norm_phone(raw)) == 13
    assert norm_phone("06832582386") == "+916832582386"
    assert norm_phone("91-81518-64492") == "+918151864492"


def test_phone_invalid():
    for raw in ["+1 415 555 0134", "883958558", "5831800366",
                "022-2006-8955", "", None, "12345678901234"]:
        assert norm_phone(raw) is None


def test_date_formats():
    assert norm_date("2026-10-31") == "2026-10-31"
    assert norm_date("27/10/2026") == "2026-10-27"
    assert norm_date("27-10-2026") == "2026-10-27"
    assert norm_date("01-Dec-2026") == "2026-12-01"
    assert norm_date("01-dec-2026") == "2026-12-01"


def test_date_day_first():
    assert norm_date("03/04/2026") == "2026-04-03"


def test_date_invalid():
    assert norm_date("31/02/2026") is None
    assert norm_date("2026-13-01") is None
    assert norm_date("garbage") is None


def test_decimal():
    assert norm_decimal("₹27,554") == Decimal("27554.00")
    assert norm_decimal("Rs. 31629") == Decimal("31629.00")
    assert norm_decimal("INR 25301.4") == Decimal("25301.40")
    assert norm_decimal("inr 10.555") == Decimal("10.56")
    assert norm_decimal("6850") == Decimal("6850.00")


def test_decimal_invalid():
    for raw in ["-", "twelve thousand", "-5", "NaN", ""]:
        assert norm_decimal(raw) is None


def test_enum():
    allowed = ["en", "hi", "ta", "kn", "te", "mr"]
    assert norm_enum(" kn ", allowed) == "kn"
    assert norm_enum("EN", allowed) == "en"
    assert norm_enum("Hindi", allowed) is None
    assert norm_enum("", allowed) is None