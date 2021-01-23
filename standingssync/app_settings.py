from .utils import clean_setting


# minimum standing a character needs to have in order to get alliance contacts
# Any char with a standing smaller than this value will be rejected
STANDINGSSYNC_CHAR_MIN_STANDING = clean_setting(
    "STANDINGSSYNC_CHAR_MIN_STANDING", default_value=0.1, min_value=-10, max_value=10
)

# When enabled will automatically add or set war targets
# with standing = -10 to synced characters
STANDINGSSYNC_ADD_WAR_TARGETS = clean_setting("STANDINGSSYNC_ADD_WAR_TARGETS", False)

# When enabled will replace contacts of synced characters with alliance contacts
STANDINGSSYNC_REPLACE_CONTACTS = clean_setting("STANDINGSSYNC_REPLACE_CONTACTS", True)
