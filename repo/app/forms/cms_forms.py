"""CMS forms."""

from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, SelectMultipleField, HiddenField, SubmitField
from wtforms.validators import DataRequired, Length, Optional


class ContentForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=300)])
    slug = StringField("Slug", validators=[Optional(), Length(max=255)])
    summary = TextAreaField("Summary", validators=[Optional(), Length(max=1000)])
    body_html = HiddenField("Body HTML")
    region_id = SelectField("Region", coerce=int, validators=[Optional()])
    media_type = SelectField("Media Type", choices=[
        ("", "-- None --"), ("article", "Article"), ("guide", "Guide"),
        ("news", "News"), ("event", "Event"), ("video", "Video"),
        ("infographic", "Infographic"),
    ], validators=[Optional()])
    categories = SelectMultipleField("Categories", coerce=int, validators=[Optional()])
    tags = SelectMultipleField("Tags", coerce=int, validators=[Optional()])
    submit = SubmitField("Save Draft")


class TaxonomyForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    submit = SubmitField("Add")


class PlacementForm(FlaskForm):
    submit = SubmitField("Update")
