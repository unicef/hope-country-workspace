from rest_framework import serializers

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
