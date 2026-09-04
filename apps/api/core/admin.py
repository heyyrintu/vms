from django.contrib import admin

from .models import NumberSequence, OrganizationSettings

admin.site.register(OrganizationSettings)
admin.site.register(NumberSequence)

