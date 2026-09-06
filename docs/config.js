// Google OAuth Client ID for the "Done" / "+30 min" calendar-sync buttons.
// Not a secret — safe to commit. It only identifies which app is asking;
// Google's own consent screen is what actually gates access.
//
// One-time setup (~5 min), at https://console.cloud.google.com/apis/credentials:
//   1. Create a project (or pick an existing one).
//   2. APIs & Services -> Library -> enable "Google Calendar API".
//   3. APIs & Services -> OAuth consent screen -> User type: External ->
//      keep Publishing status: Testing -> add yourself under "Test users".
//      (This is what stops any other visitor to this public page from being
//      able to connect their own calendar even by accident — Google refuses
//      the consent screen for anyone not on that test-user list.)
//   4. APIs & Services -> Credentials -> Create Credentials -> OAuth client ID
//      -> Application type: Web application
//      -> Authorized JavaScript origins: https://rlkemboi.github.io
//      -> Create, then copy the Client ID it gives you.
//   5. Paste it below, replacing the placeholder, and commit.
window.DAYRUN_GOOGLE_CLIENT_ID = "634826907401-es19k3cgmhqnj06lk54c93m7tpe398gk.apps.googleusercontent.com";
