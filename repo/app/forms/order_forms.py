"""Order forms."""

from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, DecimalField, SubmitField
from wtforms.validators import DataRequired, Length, Optional


class OrderForm(FlaskForm):
    customer_name = StringField("Customer Name", validators=[DataRequired(), Length(max=200)])
    customer_org = StringField("Organization", validators=[Optional(), Length(max=200)])
    service_address = TextAreaField("Service Address", validators=[Optional()])
    region_id = SelectField("Region", coerce=int, validators=[DataRequired()])
    scheduled_date = StringField("Scheduled Date (MM/DD/YYYY)", validators=[Optional()])
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Create Order")


class PaymentForm(FlaskForm):
    tender_type = SelectField("Tender Type", choices=[
        ("cash", "Cash"), ("check", "Check"), ("invoice", "Invoice"),
    ], validators=[DataRequired()])
    receipt_number = StringField("Receipt Number", validators=[DataRequired(), Length(max=100)])
    amount = DecimalField("Amount", places=2, validators=[DataRequired()])
    reference_note = StringField("Reference Note", validators=[Optional(), Length(max=300)])
    submit = SubmitField("Record Payment")


class ReconciliationForm(FlaskForm):
    label = StringField("Run Label", validators=[DataRequired(), Length(max=200)])
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Create Run")
