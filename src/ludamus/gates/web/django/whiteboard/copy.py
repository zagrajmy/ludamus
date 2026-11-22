"""The board client's words, translated here so it ships no catalog."""

from django.utils.translation import gettext as _
from django.utils.translation import pgettext


def board_copy() -> dict[str, str]:
    """Every string the board client shows, keyed as in its copy.ts.

    `%(name)s`-style placeholders are filled in by the client.

    Returns:
        The client's copy in the active language.
    """
    return {
        "addDie": _("Add %(die)s"),
        "addToPlaces": _("Add to places"),
        "boardFull": _("This board is full. You will join as soon as someone leaves."),
        "boardGone": _("This board no longer exists."),
        "bootstrapFailed": _(
            "Could not open the board. Check your connection and try again."
        ),
        "cancel": _("Cancel"),
        "clearPool": pgettext("board dice pool", "Clear"),
        "close": _("Close"),
        "connectionLost": _("Connection lost. Reconnecting…"),
        "dice": _("Dice"),
        "die": pgettext("board die, e.g. d6", "d%(sides)s"),
        "guest": pgettext("board person badge", "Guest"),
        "imagesComingSoon": _("Images are coming soon."),
        "join": _("Join the board"),
        "linkReset": _("The board's link was reset. Ask its creator for the new one."),
        "loading": _("Opening the board…"),
        "myPlace": _("My place"),
        "nameHelp": _("Others at the board see this name. Up to 40 characters."),
        "nameInvalid": _("This name cannot be used. Try another one."),
        "noPlacesYet": _(
            "No places yet. Select something on the board and add it to places."
        ),
        "noRollsYet": _("Nobody has rolled yet."),
        "people": _("People"),
        "placeName": _("Place name"),
        "places": _("Places"),
        "poolEmpty": _("Tap dice to add them to the roll."),
        "reload": _("Reload"),
        "removeDie": _("Remove %(die)s"),
        "removePlace": _("Remove from places"),
        "retry": _("Try again"),
        "roll": pgettext("board dice, a verb", "Roll"),
        "rollAgain": _("Roll again"),
        "rolledBy": _("%(name)s rolled"),
        "rollFailed": _("The roll did not go through. Try again."),
        "rollLog": _("Roll log"),
        "rollTooFast": _("Wait a moment before rolling again."),
        "save": _("Save"),
        "tooManyTries": _("Too many tries. Wait a minute, then try again."),
        "total": _("Total"),
        "you": pgettext("board person list, next to one's own name", "you"),
        "yourName": _("Your name"),
    }
