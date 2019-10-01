from django.conf import settings

# minimum standing a character needs to have in order to get alliance contacts
# Any char with a standing smaller than this value will be rejected
STANDINGSSYNC_CHAR_MIN_STANDING = getattr(
    settings, 
    'STANDINGSSYNC_CHAR_MIN_STANDING', 
    0.1
)
