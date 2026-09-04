from django.contrib import admin

from .models import (
    IntegrationConnection,
    IntegrationMessage,
    NotificationPreference,
    NotificationTemplate,
    UnmappedInboundMessage,
)

admin.site.register(IntegrationConnection)
admin.site.register(IntegrationMessage)
admin.site.register(UnmappedInboundMessage)
admin.site.register(NotificationTemplate)
admin.site.register(NotificationPreference)
