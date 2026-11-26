from country_workspace.rdp.forms import ThresholdConfigForm


class OcrConfigForm(ThresholdConfigForm):
    """Configure the OCR review threshold."""

    rate_help_text = "Findings per 100 individuals with documents submitted for OCR."
