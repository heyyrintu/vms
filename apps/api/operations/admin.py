from django.contrib import admin

from .models import (
    Client,
    Document,
    Driver,
    Indent,
    Trip,
    TripCharge,
    TripIndent,
    TripRecovery,
    Vehicle,
    Vendor,
    VendorBankAccount,
    VendorContact,
)

for model in (Client, Vendor, VendorContact, VendorBankAccount, Vehicle, Driver, Indent, Trip, TripIndent, TripCharge, Document, TripRecovery):
    admin.site.register(model)
