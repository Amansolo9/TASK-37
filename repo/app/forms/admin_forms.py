"""Admin forms."""

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SelectMultipleField, SubmitField, TextAreaField, DecimalField
from wtforms.validators import DataRequired, Length, Optional, ValidationError
from app.models.user import User


class UserForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=2, max=80)])
    display_name = StringField("Display Name", validators=[DataRequired(), Length(min=2, max=120)])
    password = PasswordField("Password", validators=[Optional(), Length(min=8)])
    is_active = BooleanField("Active", default=True)
    roles = SelectMultipleField("Roles", coerce=int)
    submit = SubmitField("Save")


class UserCreateForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=2, max=80)])
    display_name = StringField("Display Name", validators=[DataRequired(), Length(min=2, max=120)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8)])
    is_active = BooleanField("Active", default=True)
    roles = SelectMultipleField("Roles", coerce=int)
    submit = SubmitField("Save")


class RegionForm(FlaskForm):
    code = StringField("Code", validators=[DataRequired(), Length(max=20)])
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    sales_tax_rate = DecimalField("Sales Tax Rate", places=4, default=0, validators=[Optional()])
    active = BooleanField("Active", default=True)
    submit = SubmitField("Save")


class SettingForm(FlaskForm):
    value = TextAreaField("Value", validators=[Optional()])
    submit = SubmitField("Save")


class ApiClientForm(FlaskForm):
    name = StringField("Client Name", validators=[DataRequired(), Length(min=2, max=120)])
    scopes = TextAreaField("Scopes (one per line)", validators=[Optional()])
    submit = SubmitField("Create API Client")
