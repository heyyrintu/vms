from django.utils.crypto import get_random_string
from rest_framework import serializers

from .models import OTP_PURPOSE_CHOICES, User


class UserSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.display_name", read_only=True)
    password = serializers.CharField(write_only=True, required=False, min_length=12)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "whatsapp_phone",
            "role",
            "vendor",
            "vendor_name",
            "is_active",
            "mfa_enabled",
            "password",
        ]
        read_only_fields = ["id", "mfa_enabled"]

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = User(**validated_data)
        user.set_password(password or get_random_string(24))
        user.full_clean()
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if password:
            instance.set_password(password)
        instance.full_clean()
        instance.save()
        return instance


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False, write_only=True)
    otp = serializers.CharField(required=False, allow_blank=True, write_only=True)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=12)


class PasswordResetConfirmSerializer(serializers.Serializer):
    reset_ticket = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=12)


class OTPSerializer(serializers.Serializer):
    otp = serializers.CharField(min_length=6, max_length=6)
    password = serializers.CharField(required=False, write_only=True)


class OtpRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=180)
    purpose = serializers.ChoiceField(choices=OTP_PURPOSE_CHOICES)


class OtpVerifySerializer(serializers.Serializer):
    challenge_id = serializers.CharField(max_length=64)
    # `code` is the six digits delivered over WhatsApp or email. `otp` is the
    # TOTP authenticator code, named to match LoginSerializer. Both may appear.
    code = serializers.CharField(min_length=6, max_length=6)
    purpose = serializers.ChoiceField(choices=OTP_PURPOSE_CHOICES, default="LOGIN")
    otp = serializers.CharField(required=False, allow_blank=True, write_only=True)
