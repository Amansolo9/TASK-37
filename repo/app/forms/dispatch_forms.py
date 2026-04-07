"""Dispatch forms."""

from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, TextAreaField, SubmitField, TimeField
from wtforms.validators import DataRequired, Length, Optional


class ResourceForm(FlaskForm):
    resource_type = SelectField("Type", choices=[
        ("classroom", "Classroom"), ("instructor", "Instructor"), ("other", "Other"),
    ], validators=[DataRequired()])
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    code = StringField("Code", validators=[DataRequired(), Length(max=50)])
    region_id = SelectField("Region", coerce=int, validators=[Optional()])
    submit = SubmitField("Save")


class TimeSlotForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=80)])
    start_time = StringField("Start Time (HH:MM)", validators=[DataRequired()])
    end_time = StringField("End Time (HH:MM)", validators=[DataRequired()])
    submit = SubmitField("Save")


class ScheduleItemForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=200)])
    region_id = SelectField("Region", coerce=int, validators=[DataRequired()])
    scheduled_date = StringField("Date (MM/DD/YYYY)", validators=[DataRequired()])
    start_time = StringField("Start Time (HH:MM)", validators=[DataRequired()])
    end_time = StringField("End Time (HH:MM)", validators=[DataRequired()])
    classroom_id = SelectField("Classroom", coerce=int, validators=[Optional()])
    instructor_id = SelectField("Instructor", coerce=int, validators=[Optional()])
    time_slot_template_id = SelectField("Time Slot Template", coerce=int, validators=[Optional()])
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Save")
