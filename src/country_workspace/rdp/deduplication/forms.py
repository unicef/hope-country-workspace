from country_workspace.rdp.forms import ThresholdConfigForm


class BiometricDeduplicationConfigForm(ThresholdConfigForm):
    """Configure the biometric deduplication review threshold."""

    rate_label = "Findings per 100 RDP individuals"
