from django import forms

class OfficeVendorForm(forms.Form):
    username = forms.CharField(label='username', required=True)
    password = forms.CharField(label='password', widget=forms.PasswordInput(), required=True)