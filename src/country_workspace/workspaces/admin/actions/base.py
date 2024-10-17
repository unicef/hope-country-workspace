from django import forms


class BaseActionForm(forms.Form):
    # action = forms.CharField(widget=forms.HiddenInput)
    # select_across = forms.BooleanField(widget=forms.HiddenInput, required=False)
    # _selected_action = forms.CharField(widget=forms.HiddenInput)
    action = forms.CharField()
    select_across = forms.BooleanField(required=False)
    _selected_action = forms.CharField()
