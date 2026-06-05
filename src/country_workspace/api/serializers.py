from rest_framework import serializers

from country_workspace.models import Rdp


class HopeRdiCallbackSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=(
            Rdp.PushStatus.MERGED,
            Rdp.PushStatus.REJECTED,
        )
    )

    def validate_status(self, value: str) -> Rdp.PushStatus:
        return Rdp.PushStatus(value)
