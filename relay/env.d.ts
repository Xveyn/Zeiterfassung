// Secrets stehen nicht in wrangler.toml und fehlen deshalb in der generierten `worker-configuration.d.ts`
// (`wrangler types`); Einrichtung s. README.md.
interface Env {
  VAPID_PRIVATE: string;
  VAPID_SUBJECT: string;
}
