# Emptied when the legal pages moved to src/ludamus/content and
# django.contrib.flatpages was uninstalled. The file has to stay: 0009 depends
# on it by name, so deleting it would break the graph.
#
# It used to seed /privacy-policy/ and /terms-of-service/ as flatpages holding
# the literal string "<placeholder>". Keeping that body would break a fresh
# migrate outright — neither the dependency on that app nor
# apps.get_model("flatpages", ...) can resolve once it is gone.
#
# Databases that already ran it keep their rows and the django_flatpage tables.
# Nothing reads them any more; drop them whenever it suits.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("db_main", "0007_alter_agendaitem_end_time_and_more")]

    operations = []
