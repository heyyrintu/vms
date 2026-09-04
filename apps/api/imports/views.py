from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import has_capability
from audit.models import record_audit
from operations.models import Trip

from .indents import (
    build_indent_template,
    confirm_indent_import,
    preview_indent_workbook,
)
from .mis import (
    build_mis_template,
    confirm_mis_import,
    export_mis_rows,
    filter_mis_rows,
    mis_queryset,
    mis_row,
    mis_summary,
    preview_mis_workbook,
)
from .models import ImportJob
from .services import build_legacy_export, confirm_import, preview_legacy_workbook


class IndentTemplateView(APIView):
    @extend_schema(responses=bytes)
    def get(self, request):
        if not has_capability(request.user, "trips.read"):
            return Response({"detail": "Trip read permission is required"}, status=403)
        response = HttpResponse(
            build_indent_template(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="drona-indent-import-template.xlsx"'
        return response


class IndentImportPreviewView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request=dict, responses=dict)
    def post(self, request):
        if not has_capability(request.user, "trips.write"):
            return Response({"detail": "Operations permission is required"}, status=403)
        uploaded = request.FILES.get("file")
        if not uploaded:
            return Response({"detail": "XLSX file is required"}, status=400)
        if uploaded.size > 10 * 1024 * 1024:
            return Response({"detail": "File exceeds the 10 MB limit"}, status=400)
        if not uploaded.name.lower().endswith(".xlsx"):
            return Response({"detail": "Only .xlsx files are supported"}, status=400)
        from operations.models import Client

        try:
            client = Client.objects.get(pk=request.data.get("client"))
            content = uploaded.read()
            preview = preview_indent_workbook(content, client=client)
        except Client.DoesNotExist:
            return Response({"detail": "Select a valid client"}, status=400)
        except (ValueError, OSError) as exc:
            return Response({"detail": str(exc)}, status=400)
        job, _ = ImportJob.objects.get_or_create(
            source_hash=preview["source_hash"],
            defaults={
                "uploaded_by": request.user,
                "original_filename": uploaded.name[:255],
                "row_count": preview["row_count"],
                "valid_count": preview["valid_count"],
                "error_count": preview["error_count"],
                "summary": {
                    "import_kind": "INDENT",
                    "client_id": client.pk,
                    **{key: preview[key] for key in ("columns", "required_columns", "rows")},
                },
            },
        )
        if not job.original_file:
            from django.core.files.base import ContentFile

            job.original_file.save(uploaded.name, ContentFile(content), save=False)
            job.save(update_fields=["original_file", "updated_at"])
        record_audit(
            actor=request.user,
            action="INDENT_IMPORT_PREVIEWED",
            instance=job,
            after={"rows": job.row_count, "client": client.pk},
            request_id=getattr(request, "request_id", ""),
            source="IMPORT",
        )
        return Response({"job_id": job.pk, "client_id": client.pk, **preview})


class IndentImportConfirmView(APIView):
    @extend_schema(request=dict, responses=dict)
    def post(self, request, job_id):
        if not has_capability(request.user, "trips.write"):
            return Response({"detail": "Operations permission is required"}, status=403)
        job = ImportJob.objects.get(pk=job_id)
        if job.summary.get("import_kind") != "INDENT":
            return Response({"detail": "This is not an indent import job"}, status=400)
        try:
            job = confirm_indent_import(
                job=job,
                actor=request.user,
                client_id=job.summary["client_id"],
                allow_partial=bool(request.data.get("allow_partial", False)),
                request_id=getattr(request, "request_id", ""),
            )
        except (ValueError, PermissionError) as exc:
            return Response({"detail": str(exc), "result": job.result}, status=400)
        return Response({"job_id": job.pk, "status": job.status, "result": job.result})


class ExcelImportPreviewView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request=dict, responses=dict)
    def post(self, request):
        if not has_capability(request.user, "trips.write"):
            return Response({"detail": "Operations permission is required"}, status=403)
        uploaded = request.FILES.get("file")
        if not uploaded:
            return Response({"detail": "XLSX file is required"}, status=400)
        if uploaded.size > 10 * 1024 * 1024:
            return Response({"detail": "File exceeds the 10 MB limit"}, status=400)
        if not uploaded.name.lower().endswith(".xlsx"):
            return Response({"detail": "Only .xlsx files are supported"}, status=400)
        try:
            content = uploaded.read()
            preview = preview_legacy_workbook(content)
        except (ValueError, OSError) as exc:
            return Response({"detail": str(exc)}, status=400)
        job, _ = ImportJob.objects.get_or_create(
            source_hash=preview["source_hash"],
            defaults={
                "uploaded_by": request.user,
                "original_filename": uploaded.name[:255],
                "row_count": preview["row_count"],
                "valid_count": preview["valid_count"],
                "error_count": preview["error_count"],
                "summary": {key: preview[key] for key in ("columns", "required_columns", "rows")},
            },
        )
        if not job.original_file:
            from django.core.files.base import ContentFile

            job.original_file.save(uploaded.name, ContentFile(content), save=False)
            job.save(update_fields=["original_file", "updated_at"])
        record_audit(actor=request.user, action="EXCEL_IMPORT_PREVIEWED", instance=job, after={"rows": job.row_count}, request_id=getattr(request, "request_id", ""), source="IMPORT")
        return Response({"job_id": job.pk, **preview})


class ExcelImportConfirmView(APIView):
    @extend_schema(request=dict, responses=dict)
    def post(self, request, job_id):
        if not has_capability(request.user, "trips.write"):
            return Response({"detail": "Operations permission is required"}, status=403)
        job = ImportJob.objects.get(pk=job_id)
        try:
            job = confirm_import(
                job=job,
                actor=request.user,
                client_id=request.data.get("client"),
                create_missing=bool(request.data.get("create_missing", False)),
                allow_partial=bool(request.data.get("allow_partial", False)),
                import_duplicates=bool(request.data.get("import_duplicates", False)),
                request_id=getattr(request, "request_id", ""),
            )
        except (ValueError, PermissionError) as exc:
            return Response({"detail": str(exc), "result": job.result}, status=400)
        if job.status == "VALIDATION_FAILED":
            return Response(
                {
                    "detail": "Missing master data must be created or create_missing must be enabled",
                    "result": job.result,
                },
                status=400,
            )
        return Response({"job_id": job.pk, "status": job.status, "result": job.result})


class LegacyExcelExportView(APIView):
    @extend_schema(responses=bytes)
    def get(self, request):
        if not has_capability(request.user, "trips.read"):
            return Response({"detail": "Trip read permission is required"}, status=403)
        queryset = Trip.objects.all().order_by("deployment_date", "id")
        if request.user.role == "TRANSPORTER":
            queryset = queryset.filter(vendor_id=request.user.vendor_id)
        for field in ("vendor", "client", "status"):
            value = request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field if field == "status" else f"{field}_id": value})
        response = HttpResponse(
            build_legacy_export(queryset),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="npl-legacy-payment-export.xlsx"'
        return response


class MISTemplateView(APIView):
    @extend_schema(responses=bytes)
    def get(self, request):
        if not has_capability(request.user, "trips.read"):
            return Response({"detail": "Trip read permission is required"}, status=403)
        response = HttpResponse(
            build_mis_template(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="drona-mis-history-template.xlsx"'
        return response


class MISImportPreviewView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request=dict, responses=dict)
    def post(self, request):
        if getattr(request.user, "role", "") != "ADMIN":
            return Response(
                {"detail": "Only an administrator can preview historical financial imports"},
                status=403,
            )
        uploaded = request.FILES.get("file")
        if not uploaded:
            return Response({"detail": "XLSX file is required"}, status=400)
        if uploaded.size > 15 * 1024 * 1024:
            return Response({"detail": "File exceeds the 15 MB limit"}, status=400)
        if not uploaded.name.lower().endswith(".xlsx"):
            return Response({"detail": "Only .xlsx files are supported"}, status=400)
        try:
            content = uploaded.read()
            preview = preview_mis_workbook(content)
        except (ValueError, OSError) as exc:
            return Response({"detail": str(exc)}, status=400)
        job, _created = ImportJob.objects.get_or_create(
            source_hash=preview["source_hash"],
            defaults={
                "uploaded_by": request.user,
                "original_filename": uploaded.name[:255],
                "row_count": preview["row_count"],
                "valid_count": preview["valid_count"],
                "error_count": preview["error_count"],
                "summary": {
                    "kind": "MIS_HISTORY",
                    "columns": preview["columns"],
                    "required_columns": preview["required_columns"],
                    "rows": preview["rows"],
                },
            },
        )
        if job.summary.get("kind") != "MIS_HISTORY":
            return Response({"detail": "This workbook was already uploaded using another importer"}, status=409)
        if not job.original_file:
            from django.core.files.base import ContentFile

            job.original_file.save(uploaded.name, ContentFile(content), save=False)
            job.save(update_fields=["original_file", "updated_at"])
        record_audit(
            actor=request.user,
            action="MIS_HISTORY_PREVIEWED",
            instance=job,
            after={"rows": job.row_count, "valid": job.valid_count, "errors": job.error_count},
            request_id=getattr(request, "request_id", ""),
            source="IMPORT",
        )
        return Response({"job_id": job.pk, "status": job.status, **preview})


class MISImportConfirmView(APIView):
    @extend_schema(request=dict, responses=dict)
    def post(self, request, job_id):
        if getattr(request.user, "role", "") != "ADMIN":
            return Response(
                {"detail": "Only an administrator can post historical financial records"},
                status=403,
            )
        job = ImportJob.objects.filter(pk=job_id).first()
        if not job:
            return Response({"detail": "Import job not found"}, status=404)
        try:
            job = confirm_mis_import(
                job=job,
                actor=request.user,
                create_missing=bool(request.data.get("create_missing", True)),
                allow_partial=bool(request.data.get("allow_partial", False)),
                request_id=getattr(request, "request_id", ""),
            )
        except (ValueError, PermissionError) as exc:
            return Response({"detail": str(exc), "result": job.result}, status=400)
        return Response({"job_id": job.pk, "status": job.status, "result": job.result})


class MISImportHistoryView(APIView):
    @extend_schema(responses=dict)
    def get(self, request):
        if not has_capability(request.user, "trips.read"):
            return Response({"detail": "Trip read permission is required"}, status=403)
        jobs = ImportJob.objects.filter(summary__kind="MIS_HISTORY").select_related("uploaded_by").order_by("-created_at")[:25]
        return Response(
            [
                {
                    "id": job.pk,
                    "filename": job.original_filename,
                    "status": job.status,
                    "row_count": job.row_count,
                    "valid_count": job.valid_count,
                    "error_count": job.error_count,
                    "uploaded_by": job.uploaded_by.get_full_name() or job.uploaded_by.username,
                    "created_at": job.created_at,
                    "confirmed_at": job.confirmed_at,
                    "result": job.result,
                }
                for job in jobs
            ]
        )


class MISRecordsView(APIView):
    @extend_schema(responses=dict)
    def get(self, request):
        if not has_capability(request.user, "trips.read"):
            return Response({"detail": "Trip read permission is required"}, status=403)
        rows = [mis_row(trip) for trip in mis_queryset(request.query_params, request.user)]
        rows = filter_mis_rows(rows, request.query_params.get("payment_status", "").upper())
        summary = mis_summary(rows)
        if request.query_params.get("format") == "xlsx":
            response = HttpResponse(
                export_mis_rows(rows),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = 'attachment; filename="drona-mis-register.xlsx"'
            return response
        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = min(200, max(1, int(request.query_params.get("page_size", 50))))
        except ValueError:
            return Response({"detail": "Page values must be numbers"}, status=400)
        start = (page - 1) * page_size
        return Response(
            {
                "count": len(rows),
                "page": page,
                "page_size": page_size,
                "summary": summary,
                "rows": rows[start : start + page_size],
            }
        )
