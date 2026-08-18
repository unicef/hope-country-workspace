from rest_framework import serializers

from .types import PushReadyCallbackCode


class HopeRdpPushReadyCallbackPayloadSerializer(serializers.Serializer):
    """Validate a signed HOPE push-ready callback payload."""

    rdp_id = serializers.IntegerField(min_value=1)
    push_attempt_id = serializers.UUIDField()


class HopeRdpPushReadyCallbackRequestSerializer(serializers.Serializer):
    """Validate a HOPE push-ready callback request."""

    signed_token = serializers.CharField()


class HopeRdpPushReadyCallbackResponseSerializer(serializers.Serializer):
    """Serialize a HOPE push-ready callback response."""

    rdp_id = serializers.IntegerField()
    push_attempt_id = serializers.UUIDField()
    code = serializers.ChoiceField(choices=PushReadyCallbackCode)
    detail = serializers.CharField()


class HopeRdpPushReadyCallbackErrorSerializer(serializers.Serializer):
    """Serialize a HOPE push-ready callback error response."""

    detail = serializers.CharField()
