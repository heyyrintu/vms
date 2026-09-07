import uuid

from django.conf import settings
from django.contrib.auth import (
    authenticate,
    login,
    logout,
    password_validation,
    update_session_auth_hash,
)
from django.contrib.auth.tokens import default_token_generator
from django.core.signing import TimestampSigner
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import record_audit
from core.crypto import decrypt_value, encrypt_value

from . import otp as otp_service
from .mfa import generate_secret, provisioning_uri, verify_code
from .models import OtpChallenge, User
from .serializers import (
    LoginSerializer,
    OtpRequestSerializer,
    OTPSerializer,
    OtpVerifySerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    UserSerializer,
)


class AdminUserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    queryset = User.objects.select_related("vendor").order_by("username")
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_permissions(self):
        return [IsAuthenticated()]

    def _allowed(self, request):
        return request.user.role == User.Role.ADMIN

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not self._allowed(request):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Administrator permission is required")


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CSRFView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=dict)
    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "login"

    @extend_schema(request=LoginSerializer, responses=UserSerializer)
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credentials = serializer.validated_data.copy()
        otp = credentials.pop("otp", "")
        user = authenticate(request, **credentials)
        if user is None or not user.is_active:
            return Response({"detail": "Invalid credentials"}, status=status.HTTP_400_BAD_REQUEST)
        if user.mfa_enabled and not verify_code(decrypt_value(user.mfa_secret_encrypted), otp):
            return Response({"detail": "A valid authenticator code is required", "mfa_required": True}, status=400)
        login(request, user)
        return Response(UserSerializer(user).data)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=UserSerializer)
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PasswordChangeSerializer, responses=dict)
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not request.user.check_password(serializer.validated_data["current_password"]):
            return Response({"detail": "Current password is incorrect"}, status=400)
        password = serializer.validated_data["new_password"]
        password_validation.validate_password(password, request.user)
        request.user.set_password(password)
        request.user.save(update_fields=["password"])
        # Keeps this session valid while every other session's auth hash goes stale.
        update_session_auth_hash(request, request.user)
        return Response({"status": "password_changed"})


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "password_reset"

    @extend_schema(request=PasswordResetRequestSerializer, responses=dict)
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=serializer.validated_data["email"], is_active=True).first()
        if user:
            from integrations.services import queue_message

            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            base_url = settings.WEB_ORIGIN
            reset_url = f"{base_url}/login?reset_uid={uid}&reset_token={token}"
            queue_message(
                channel="EMAIL",
                recipient=user.email,
                subject="Reset your Drona Logitech password",
                body=f"Use this secure link to reset your password: {reset_url}",
                object_type="account",
                object_id=str(user.pk),
                idempotency_key=f"password-reset:{user.pk}:{token[-8:]}",
                user=user,
                event_key="PASSWORD_RESET",
            )
        return Response({"status": "If the account exists, reset instructions have been queued."})


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "password_reset"

    @extend_schema(request=PasswordResetConfirmSerializer, responses=dict)
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(serializer.validated_data["uid"])))
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            user = None
        if not user or not default_token_generator.check_token(user, serializer.validated_data["token"]):
            return Response({"detail": "Reset link is invalid or expired"}, status=400)
        password = serializer.validated_data["new_password"]
        password_validation.validate_password(password, user)
        user.set_password(password)
        user.save(update_fields=["password"])
        return Response({"status": "password_reset"})


class MFASetupView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses=dict)
    def post(self, request):
        if request.user.mfa_enabled:
            return Response({"detail": "MFA is already enabled. Disable it using your password and authenticator code before setting it up again."}, status=400)
        secret = generate_secret()
        request.user.mfa_secret_encrypted = encrypt_value(secret)
        request.user.mfa_enabled = False
        request.user.save(update_fields=["mfa_secret_encrypted", "mfa_enabled"])
        return Response(
            {
                "secret": secret,
                "provisioning_uri": provisioning_uri(
                    secret=secret,
                    username=request.user.username,
                    issuer="Drona Logitech",
                ),
            }
        )


class MFAConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=OTPSerializer, responses=dict)
    def post(self, request):
        serializer = OTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        secret = decrypt_value(request.user.mfa_secret_encrypted)
        if not secret or not verify_code(secret, serializer.validated_data["otp"]):
            return Response({"detail": "Invalid authenticator code"}, status=400)
        request.user.mfa_enabled = True
        request.user.save(update_fields=["mfa_enabled"])
        return Response({"status": "mfa_enabled"})


class MFADisableView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=OTPSerializer, responses=dict)
    def post(self, request):
        serializer = OTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not request.user.check_password(serializer.validated_data.get("password", "")):
            return Response({"detail": "Password is required to disable MFA"}, status=400)
        if not verify_code(decrypt_value(request.user.mfa_secret_encrypted), serializer.validated_data["otp"]):
            return Response({"detail": "Invalid authenticator code"}, status=400)
        request.user.mfa_enabled = False
        request.user.mfa_secret_encrypted = ""
        request.user.save(update_fields=["mfa_enabled", "mfa_secret_encrypted"])
        return Response({"status": "mfa_disabled"})


class OtpRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "otp_request"

    @extend_schema(request=OtpRequestSerializer, responses=dict)
    def post(self, request):
        serializer = OtpRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data["identifier"].strip()
        purpose = serializer.validated_data["purpose"]
        user, channel = otp_service.resolve_identifier(identifier)
        expires_in = int(otp_service.CODE_TTL.total_seconds())
        if user is None or (channel == OtpChallenge.Channel.EMAIL and not user.email):
            # Answer unknown identifiers with the same shape so the endpoint
            # cannot be used to discover which accounts exist.
            return Response({
                "challenge_id": str(uuid.uuid4()),
                "channel": channel,
                "destination_masked": otp_service.mask_destination(identifier),
                "expires_in": expires_in,
            })
        try:
            challenge, code = otp_service.issue_challenge(
                user, purpose=purpose, channel=channel, request=request
            )
        except otp_service.OtpRateLimited:
            return Response({"detail": "Too many code requests. Try again shortly."}, status=429)
        otp_service.send_challenge(challenge, code)
        record_audit(actor=request.user, action="OTP_ISSUED", instance=challenge,
                     after={"purpose": purpose, "channel": channel})
        return Response({
            "challenge_id": str(challenge.id),
            "channel": challenge.channel,
            "destination_masked": challenge.destination_masked,
            "expires_in": expires_in,
        })


class OtpVerifyView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "otp_verify"

    @extend_schema(request=OtpVerifySerializer, responses=dict)
    def post(self, request):
        serializer = OtpVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        purpose = serializer.validated_data["purpose"]
        try:
            challenge = otp_service.verify_challenge(
                serializer.validated_data["challenge_id"],
                serializer.validated_data["code"],
                purpose=purpose,
            )
        except otp_service.OtpInvalid:
            return Response({"detail": "Invalid or expired code"}, status=400)

        user = challenge.user
        if not user.is_active:
            # Deactivation can race a valid, unexpired code. Reject exactly
            # like a wrong/expired code so this endpoint never signals
            # account status, and leave the challenge for natural expiry
            # rather than consuming it.
            return Response({"detail": "Invalid or expired code"}, status=400)

        if purpose == OtpChallenge.Purpose.PASSWORD_RESET:
            otp_service.consume(challenge)
            record_audit(actor=None, action="OTP_VERIFIED", instance=challenge)
            ticket = TimestampSigner().sign_object(
                {"user": user.pk, "challenge": str(challenge.id)}
            )
            return Response({"reset_ticket": ticket})

        if user.mfa_enabled and not verify_code(
            decrypt_value(user.mfa_secret_encrypted), serializer.validated_data.get("otp", "")
        ):
            # Keep the challenge alive so the user can retry with their
            # authenticator, but count the try so it cannot be ground down.
            otp_service.register_failed_attempt(challenge)
            return Response(
                {"detail": "A valid authenticator code is required", "mfa_required": True},
                status=400,
            )
        otp_service.consume(challenge)
        login(request, user)
        record_audit(actor=user, action="OTP_LOGIN", instance=challenge)
        return Response(UserSerializer(user).data)
