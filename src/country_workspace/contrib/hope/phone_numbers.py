from django import forms

from country_workspace.validators.phone_number import is_right_phone_number_format


class PhoneNumberField(forms.CharField):
    def clean(self, value: str) -> str:
        value = super().clean(value)

        if value and not is_right_phone_number_format(value):
            raise forms.ValidationError("Invalid phone number")

        return value
