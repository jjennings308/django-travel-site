-- Disguise a copy of production for staging (site roadmap R16), run by sync_staging_from_prod.sh
-- right after the restore. Staging can't send mail anyway; this keeps real addresses, phone numbers
-- and travel-document numbers out of a second database. Safe to run twice.
BEGIN;
-- Accounts: everyone signs in on staging with user<id>@staging.invalid (their usual password).
UPDATE users SET email = 'user' || id || '@staging.invalid', phone_number = '', date_of_birth = NULL
 WHERE email NOT LIKE '%@staging.invalid';
-- Travel documents.
UPDATE trips_traveler SET passport_number = '', known_traveler_number = '', redress_number = '',
       passport_expires = NULL;
-- Contacts and invitations on trips.
UPDATE trips_contact SET email = CASE WHEN email = '' THEN '' ELSE 'contact' || id || '@staging.invalid' END;
UPDATE trips_tripinvite SET email = 'invite' || id || '@staging.invalid';
-- Nothing queued to email from the copy.
UPDATE trips_tripchange SET digest_sent_at = now() WHERE digest_sent_at IS NULL;
COMMIT;
