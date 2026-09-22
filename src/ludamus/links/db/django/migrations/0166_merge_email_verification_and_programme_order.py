from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("db_main", "0161_merge_0159_alter_notification_kind_0160_eventmappage"),
        ("db_main", "0165_sphere_subscriptions"),
    ]

    # Both branches rewrote Notification.kind's choices; each dropped the
    # other's new kinds. Restate the union so the column matches the enum.
    operations = [
        migrations.AlterField(
            model_name="notification",
            name="kind",
            field=models.CharField(
                choices=[
                    ("waitlist_promoted", "WAITLIST_PROMOTED"),
                    ("waitlist_offer", "WAITLIST_OFFER"),
                    ("offer_expired", "OFFER_EXPIRED"),
                    ("shadowbanned_signup", "SHADOWBANNED_SIGNUP"),
                    ("party_invite", "PARTY_INVITE"),
                    ("party_enrolled", "PARTY_ENROLLED"),
                    ("party_seat_held", "PARTY_SEAT_HELD"),
                    ("printables_ready", "PRINTABLES_READY"),
                    ("email_verification", "EMAIL_VERIFICATION"),
                    ("email_change_requested", "EMAIL_CHANGE_REQUESTED"),
                    ("email_change_completed", "EMAIL_CHANGE_COMPLETED"),
                    ("sphere_event_published", "SPHERE_EVENT_PUBLISHED"),
                ],
                max_length=32,
            ),
        )
    ]
