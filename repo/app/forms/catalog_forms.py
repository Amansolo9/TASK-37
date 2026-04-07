"""Catalog forms."""

from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, DecimalField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Length, Optional


class ServiceItemForm(FlaskForm):
    code = StringField("Code", validators=[DataRequired(), Length(max=50)])
    name = StringField("Name", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("Description", validators=[Optional()])
    pricing_model = SelectField("Pricing Model", choices=[
        ("hourly", "Hourly"), ("per_use", "Per Use"), ("package", "Package"),
    ], validators=[DataRequired()])
    unit_rate = DecimalField("Unit Rate", places=2, validators=[Optional()])
    package_price = DecimalField("Package Price", places=2, validators=[Optional()])
    cost_amount = DecimalField("Cost Amount", places=2, validators=[Optional()])
    taxable = BooleanField("Taxable", default=True)
    submit = SubmitField("Save")
