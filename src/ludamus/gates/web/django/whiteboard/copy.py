"""The board client's words, translated here so it ships no catalog."""

from django.utils.translation import gettext as _


def board_copy() -> dict[str, str]:
    return {
        "dice": _("Dice"),
        "roll": _("Roll"),
        "rollAgain": _("Roll again"),
        "rollLog": _("Roll log"),
        "noRollsYet": _("Nobody has rolled yet."),
        "places": _("Places"),
        "addToPlaces": _("Add to places"),
        "placeName": _("Place name"),
        "noPlacesYet": _(
            "No places yet. Select something on the board and add it to places."
        ),
        "removePlace": _("Remove place"),
        "myPlace": _("My place"),
        "people": _("People"),
        "guest": _("Guest"),
        "yourName": _("Your name"),
        "join": _("Join the board"),
        "nameHelp": _("Others at the board see this name. Up to 40 characters."),
        "connectionLost": _("Connection lost. Reconnecting…"),
        "linkReset": _("The board's link was reset. Ask its creator for the new one."),
        "boardFull": _("This board is full. Try again later."),
        "total": _("Total"),
    }
