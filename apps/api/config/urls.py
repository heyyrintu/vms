from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from accounts.views import (
    AdminUserViewSet,
    CSRFView,
    LoginView,
    LogoutView,
    MeView,
    MFAConfirmView,
    MFADisableView,
    MFASetupView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
)
from approvals.views import ApprovalBatchViewSet, ApprovalRuleViewSet, CommentViewSet
from audit.views import AuditLogViewSet
from core.views import (
    ChoicesView,
    GlobalSearchView,
    HealthView,
    PermissionMatrixView,
    ReadinessView,
    SettingsView,
)
from imports.views import (
    ExcelImportConfirmView,
    ExcelImportPreviewView,
    IndentImportConfirmView,
    IndentImportPreviewView,
    IndentTemplateView,
    LegacyExcelExportView,
    MISImportConfirmView,
    MISImportHistoryView,
    MISImportPreviewView,
    MISRecordsView,
    MISTemplateView,
)
from integrations.views import (
    EmailWebhookView,
    IntegrationConnectionViewSet,
    IntegrationMessageViewSet,
    NotificationPreferenceViewSet,
    NotificationTemplateViewSet,
    UnmappedInboundViewSet,
    WhatsAppWebhookView,
)
from operations.views import (
    ClientViewSet,
    DocumentViewSet,
    DriverViewSet,
    IndentViewSet,
    TripRecoveryViewSet,
    TripViewSet,
    VehicleViewSet,
    VendorBankAccountViewSet,
    VendorContactViewSet,
    VendorViewSet,
)
from payments.views import (
    ClientBillingViewSet,
    DashboardView,
    FinalTripSettlementViewSet,
    FinancePendingView,
    PaymentViewSet,
    ReportCatalogView,
    ReportView,
    TDSEntryViewSet,
    TripLedgerView,
    VendorLedgerView,
)

router = DefaultRouter()
router.register("clients", ClientViewSet, basename="client")
router.register("vendors", VendorViewSet, basename="vendor")
router.register("vendor-contacts", VendorContactViewSet, basename="vendor-contact")
router.register("vendor-bank-accounts", VendorBankAccountViewSet, basename="vendor-bank-account")
router.register("vehicles", VehicleViewSet, basename="vehicle")
router.register("drivers", DriverViewSet, basename="driver")
router.register("indents", IndentViewSet, basename="indent")
router.register("trips", TripViewSet, basename="trip")
router.register("approval-batches", ApprovalBatchViewSet, basename="approval-batch")
router.register("payments", PaymentViewSet, basename="payment")
router.register("tds", TDSEntryViewSet, basename="tds")
router.register("audit", AuditLogViewSet, basename="audit")
router.register("users", AdminUserViewSet, basename="user")
router.register("approval-rules", ApprovalRuleViewSet, basename="approval-rule")
router.register("comments", CommentViewSet, basename="comment")
router.register("documents", DocumentViewSet, basename="document")
router.register("recoveries", TripRecoveryViewSet, basename="recovery")
router.register("settlements", FinalTripSettlementViewSet, basename="settlement")
router.register("billings", ClientBillingViewSet, basename="billing")
router.register("messages", IntegrationMessageViewSet, basename="message")
router.register("notification-templates", NotificationTemplateViewSet, basename="notification-template")
router.register("notification-preferences", NotificationPreferenceViewSet, basename="notification-preference")
router.register("integration-connections", IntegrationConnectionViewSet, basename="integration-connection")
router.register("unmapped-messages", UnmappedInboundViewSet, basename="unmapped-message")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", HealthView.as_view()),
    path("api/readiness/", ReadinessView.as_view()),
    path("api/auth/csrf/", CSRFView.as_view()),
    path("api/auth/login/", LoginView.as_view()),
    path("api/auth/logout/", LogoutView.as_view()),
    path("api/auth/me/", MeView.as_view()),
    path("api/auth/password/change/", PasswordChangeView.as_view()),
    path("api/auth/password/reset/", PasswordResetRequestView.as_view()),
    path("api/auth/password/reset/confirm/", PasswordResetConfirmView.as_view()),
    path("api/auth/mfa/setup/", MFASetupView.as_view()),
    path("api/auth/mfa/confirm/", MFAConfirmView.as_view()),
    path("api/auth/mfa/disable/", MFADisableView.as_view()),
    path("api/settings/", SettingsView.as_view()),
    path("api/choices/", ChoicesView.as_view()),
    path("api/permission-matrix/", PermissionMatrixView.as_view()),
    path("api/search/", GlobalSearchView.as_view()),
    path("api/dashboard/", DashboardView.as_view()),
    path("api/finance/pending/", FinancePendingView.as_view()),
    path("api/vendor-ledger/<int:vendor_id>/", VendorLedgerView.as_view()),
    path("api/trip-ledger/<int:trip_id>/", TripLedgerView.as_view()),
    path("api/imports/excel/preview/", ExcelImportPreviewView.as_view()),
    path("api/imports/excel/<int:job_id>/confirm/", ExcelImportConfirmView.as_view()),
    path("api/imports/excel/export/", LegacyExcelExportView.as_view()),
    path("api/imports/indents/template/", IndentTemplateView.as_view()),
    path("api/imports/indents/preview/", IndentImportPreviewView.as_view()),
    path("api/imports/indents/<int:job_id>/confirm/", IndentImportConfirmView.as_view()),
    path("api/mis/records/", MISRecordsView.as_view()),
    path("api/mis/template/", MISTemplateView.as_view()),
    path("api/mis/imports/", MISImportHistoryView.as_view()),
    path("api/mis/import/preview/", MISImportPreviewView.as_view()),
    path("api/mis/import/<int:job_id>/confirm/", MISImportConfirmView.as_view()),
    path("api/reports/", ReportCatalogView.as_view()),
    path("api/reports/<slug:slug>/", ReportView.as_view()),
    path("api/webhooks/email/", EmailWebhookView.as_view()),
    path("api/webhooks/whatsapp/", WhatsAppWebhookView.as_view()),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/", include(router.urls)),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
