from rest_framework import serializers

from country_workspace.contrib.hope.push.config import HopeRdiCallbackCode
from country_workspace.models import Rdp


class HopeRdiCallbackSerializer(serializers.Serializer):
    """Validate HOPE RDI final status callback payload."""

    status = serializers.ChoiceField(
        choices=(
            Rdp.PushStatus.MERGED,
            Rdp.PushStatus.REJECTED,
        ),
    )

    def validate_status(self, value: str) -> Rdp.PushStatus:
        """Return status as Rdp.PushStatus."""
        return Rdp.PushStatus(value)


class HopeRdiCallbackPayloadSerializer(serializers.Serializer):
    """Serialize HOPE RDI callback response payload."""

    rdp_id = serializers.IntegerField(allow_null=True)
    rdi_id = serializers.CharField(allow_null=True)
    status = serializers.ChoiceField(choices=Rdp.PushStatus.choices, allow_null=True)
    code = serializers.ChoiceField(choices=[(code.value, code.value) for code in HopeRdiCallbackCode])
    detail = serializers.CharField()


class HopeRdiCallbackValidationErrorSerializer(serializers.Serializer):
    """Serialize callback request validation errors."""

    status = serializers.ListField(child=serializers.CharField(), required=False)
    detail = serializers.CharField(required=False)
