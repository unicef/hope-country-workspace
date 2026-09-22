from rest_framework import serializers

from .types import DedupCallbackCode


class DedupEngineRdpCallbackPayloadSerializer(serializers.Serializer):
    """Validate a signed DedupEngine RDP callback payload."""

    rdp_id = serializers.IntegerField(min_value=1)
    deduplication_set_id = serializers.UUIDField()


class DedupEngineRdpCallbackResponseSerializer(serializers.Serializer):
    """Serialize a DedupEngine RDP callback response."""

    code = serializers.ChoiceField(choices=DedupCallbackCode)
    detail = serializers.CharField()


class DedupEngineRdpCallbackErrorSerializer(serializers.Serializer):
    """Serialize a DedupEngine RDP callback error response."""

    detail = serializers.CharField()
