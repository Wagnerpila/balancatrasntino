from django import forms 

class UserForm(forms.Form):
    user_id = forms.IntegerField(label='User ID')
    user_name = forms.CharField(label='User Name', max_length=100)
    user_type = forms.CharField(label='User Type', max_length=50)
    doors = forms.CharField(label='Doors', max_length=100)
    time_sections = forms.CharField(label='Time Sections', max_length=100)
    valid_from = forms.DateTimeField(label='Valid From')
    valid_to = forms.DateTimeField(label='Valid To')


    