import lark from "@larksuiteoapi/node-sdk";

const APP_ID = "cli_a9f23f624b649ceb";
const APP_SECRET = "F4aHJepltjOioMCyDW0zWfvDwKrpdHeQ";
const VERIFICATION_TOKEN = "46ndboTsb1vR69qIy4nlhcABQj2Gwys1";
const ENCRYPT_KEY = "sU6WkPbol3PysSruSxVI6bm1JB7nRkd2";

const eventDispatcher = new lark.EventDispatcher({
  verificationToken: VERIFICATION_TOKEN,
  encryptKey: ENCRYPT_KEY,
}).register({
  "im.message.receive_v1": async (data) => {
    console.log("=== RECEIVED MESSAGE ===");
    console.log(JSON.stringify(data, null, 2));
    console.log("========================");
  },
});

const wsClient = new lark.WSClient({
  appId: APP_ID,
  appSecret: APP_SECRET,
  loggerLevel: lark.LoggerLevel.DEBUG,
});

wsClient.start({ eventDispatcher });

setInterval(() => {
  console.log(`[heartbeat] ${new Date().toISOString()} - still waiting...`);
}, 30000);

console.log("Test started with verificationToken + encryptKey.");
console.log("Send a message to the bot NOW!");
