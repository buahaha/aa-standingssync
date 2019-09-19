# standingssync

This is a plugin app for Alliance Auth. It allows users to have the current alliance standings on their non-alliance characters (e.g. alts).

## Features

- Appears as app in the sidebar of AA called "Standings Sync"
- Users can add / remove their characters for syncing via app
- Added characters get synchronised with current alliance standings until removed
- Multiple alliances can be setup for synchronisation
- App chooses alliance for sync based on memberships of the user
- Admins can inspect sync status and manually re-start syncing for alliance and characters

## Screenshot

Here is a screenshot of the main screen.

![Main Screen](https://i.imgur.com/xGdoqsp.png)

## How it works

To enable non-alliance members to use alliance standings the personal contact of that character are replaced with the alliance contacts.

## Installation

1. Install into AA virtual environment with PIP install from this repo

   ```bash
   pip install git+https://gitlab.com/ErikKalkoken/aa-standingssync
   ```

1. Configure your AA settings (`local.py`)
   - Add `'standingssync'` to `INSTALLED_APPS`
   - Add these lines:

   ```python
   CELERYBEAT_SCHEDULE['standingssync.run_regular_sync'] = {
    'task': 'evesde.tasks.run_update',
    'schedule': crontab(minute=0, hour='*/4'),
    'kwargs': {'report_mode': 'events'}
   }
   ```

   > **Note**:<br>This configures the sync process to run every 4 hours starting at 00:00 AM UTC. Feel free to adjust the timing to the needs of you alliance.<br>However, do not schedule it too tightly. Or you risk generating more and more tasks, when sync tasks from previous runs are not able to finish within the alloted time.

1. Run migrations

1. Restart your supervisor services for AA

1. Setup permissions

## Permissions

This app only uses two permission. One for enabling this app for users and one for enabling users to add alliances for syncing.

Purpose | name | code
-- | -- | --
Enabling the app for a user. This permission should be enabled for everyone who is allowed to use the app (e.g. Member state) | Can add synced character | add_syncedcharacter
Enables adding alliances for syncing by setting the character for fetching alliance contacts. This should be limited to users with admins / leadership priviledges. | Can add alliance manager | add_alliancemanager
