# Deliberately empty. 0009 depends on this migration by name, so the file has to
# stay even though nothing it did survives.
#
# It seeded /privacy-policy/ and /terms-of-service/ as django.contrib.flatpages
# rows holding the literal string "<placeholder>". That app is not installed, so
# neither a dependency on it nor apps.get_model("flatpages", ...) resolves, and
# a fresh migrate would fail on the old body.
#
# Databases that already ran it keep their rows and the django_flatpage tables.
# Nothing reads them any more; drop them whenever it suits.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("db_main", "0007_alter_agendaitem_end_time_and_more")]

    operations = []
