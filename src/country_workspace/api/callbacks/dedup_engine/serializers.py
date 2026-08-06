from rest_framework import serializers


class DeduplicationCallbackTokenSerializer(serializers.Serializer):
    """Validate a signed DedupEngine callback payload."""

    rdp_id = serializers.IntegerField(min_value=1)
    job_id = serializers.IntegerField(min_value=1)


class DeduplicationCallbackErrorSerializer(serializers.Serializer):
    """Serialize a DedupEngine callback error response."""

    detail = serializers.CharField()
