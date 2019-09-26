# standingssync

This is a plugin app for [Alliance Auth](https://gitlab.com/allianceauth/allianceauth). Users can choose to get the current alliance standings on their non-alliance characters (e.g. alts).

![License](https://img.shields.io/badge/license-MIT-green) ![python](https://img.shields.io/badge/python-3.5-informational) ![AA](https://img.shields.io/badge/AllianceAuth-2.2-informational)

Current status: **BETA**

## Features

The main purpose of this app is to enable non-alliance characters to have the same standings view than their alliance main.

Here is an high level overview of the main features:

- Synchronize alliance standings / contacts to non-alliance characters
- Users can choose which of their characters shall be synchronized
- Supports multiple alliances
- Synchronization is ongoing until user chooses to remove character from synchronization
- Should the user loose permissions or his token become invalid or a character loose alliance standing sync is deactivated for those characters
- User can only add sync to characters that have good standing with the alliance

## Screenshot

Here is a screenshot of the main screen.

![Main Screen](https://i.imgur.com/xGdoqsp.png)

## How it works

To enable non-alliance members to use alliance standings the personal contact of that character are replaced with the alliance contacts.

## Installation

### 1. Install app

Install into AA virtual environment with PIP install from this repo:

```bash
pip install git+https://gitlab.com/ErikKalkoken/aa-standingssync.git
```

### 2 Update Eve Online app

Update the Eve Online app used for authentication in your AA installation to include the following scopes:

```plain
esi-characters.read_contacts.v1
esi-characters.write_contacts.v1
esi-alliances.read_contacts.v1
```

### 3. Configure AA settings

Configure your AA settings (`local.py`) as follows:

- Add `'standingssync'` to `INSTALLED_APPS`
- Add these lines add to bottom of your settings file:

   ```python
   # settings for standingssync
   CELERYBEAT_SCHEDULE['standingssync.run_regular_sync'] = {
       'task': 'standingssync.tasks.run_regular_sync',
       'schedule': crontab(minute=0, hour='*/2')
   }
   ```

   > **Note**:<br>This configures the sync process to run every 2 hours starting at 00:00 AM UTC. Feel free to adjust the timing to the needs of you alliance.<br>However, do not schedule it too tightly. Or you risk generating more and more tasks, when sync tasks from previous runs are not able to finish within the alloted time.

### 4. Finalize installation into AA

Run migrations & copy static files

```bash
python manage.py migrate
python manage.py collectstatic
```

Restart your supervisor services for AA

### 5. Setup permissions

Now you can access Alliance Auth and setup permissions for your users. See section "Permissions" below for details.

### 6. Setup alliance character

Finally you need to set the alliance character that will be used for fetching the alliance contacts / standing. Just click on "Set Alliance Character" and add the requested token. Note that only users with the appropriate permission will be able to see and use this function.

Once an alliance character is set the app will immediately start fetching alliance contacts. Wait a minute and then reload the page to see the result.

That's it. The Standing Sync app is fully installed and ready to be used.
  
## Permissions

This app only uses two permission. One for enabling this app for users and one for enabling users to add alliances for syncing.

Purpose | name | code
-- | -- | --
Enabling the app for a user. This permission should be enabled for everyone who is allowed to use the app (e.g. Member state) | Can add synced character | add_syncedcharacter
Enables adding alliances for syncing by setting the character for fetching alliance contacts. This should be limited to users with admins / leadership privileges. | Can add alliance manager | add_alliancemanager

## Admin functions

Admins will find a "Standings Sync" section on the admin page. This section provides the following features:

- See a list of all setup alliances with their sync status

- See a list of all enabled characters with their current sync status

- Manually remove characters / alliances from sync

- Manually start the sync process for characters / alliances
