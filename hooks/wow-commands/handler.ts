import { execSync } from "child_process";
import { homedir } from "os";
import { join } from "path";

const SCRIPTS_DIR = join(homedir(), ".openclaw", "scripts");

const COMMANDS: Record<string, string> = {
  "!strat": "cmd-strat.sh",
  "!gearcheck": "cmd-gearcheck.sh",
  "!gearprio": "cmd-gearprio.sh",
  "/strat": "cmd-strat.sh",
  "/gearcheck": "cmd-gearcheck.sh",
  "/gearprio": "cmd-gearprio.sh",
};

function cleanContent(raw: string): string {
  return raw
    .replace(/<@!?\d+>/g, "")
    .replace(/@\w+/g, "")
    .trim();
}

function matchCommand(cleaned: string): { cmd: string; script: string; args: string } | null {
  for (const [cmd, script] of Object.entries(COMMANDS)) {
    if (cleaned.toLowerCase().startsWith(cmd.toLowerCase())) {
      return { cmd, script, args: cleaned.substring(cmd.length).trim() };
    }
  }
  return null;
}

export default async (event: any) => {
  const eventKey = `${event.type}:${event.action}`;

  // We only act on message:received — it's the only event that consistently fires
  // and has the raw content before OpenClaw wraps it
  if (event.type !== "message" || event.action !== "received") {
    return;
  }

  const content: string = (event.context?.content || "").trim();
  if (!content) return;

  const cleaned = cleanContent(content);
  const match = matchCommand(cleaned);

  if (!match) return;

  console.log(`[wow-commands] INTERCEPTED: ${match.cmd} args="${match.args}"`);

  try {
    const scriptPath = join(SCRIPTS_DIR, match.script);
    const result = execSync(`bash "${scriptPath}" ${match.args}`, {
      encoding: "utf-8",
      timeout: 30000,
      env: { ...process.env, HOME: homedir() },
    }).trim();

    console.log(`[wow-commands] OUTPUT: ${result.length} chars`);

    // Push response into the event's messages array — this is how hooks send messages
    if (event.messages && Array.isArray(event.messages)) {
      event.messages.push(result);
      console.log(`[wow-commands] pushed to event.messages`);
    }

    // Also try returning handled to stop further processing
    return { handled: true, text: result };
  } catch (err: any) {
    const msg = `Error running ${match.cmd}: ${err.stderr?.toString() || err.message || "unknown error"}`;
    console.log(`[wow-commands] ERROR: ${msg.substring(0, 200)}`);
    if (event.messages && Array.isArray(event.messages)) {
      event.messages.push(msg);
    }
    return { handled: true, text: msg };
  }
};
