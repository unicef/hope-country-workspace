from django import forms

from country_workspace.validators.phone_number import is_right_phone_number_format, is_valid_phone_number


class PhoneNumberField(forms.CharField):
    def clean(self, value: str) -> str:
        value = super().clean(value)

        if value:
            is_right, formatted_number = is_right_phone_number_format(value)
            if not is_right:
                raise forms.ValidationError("Invalid phone number format.")
            value = formatted_number

            if not is_valid_phone_number(value):
                raise forms.ValidationError("Invalid phone number.")

        return value
