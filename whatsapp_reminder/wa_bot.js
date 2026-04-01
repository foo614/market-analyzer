const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const cron = require('node-cron');

// Initialize the client with LocalAuth to save session and support auto-reconnect
const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        headless: false, // Set to false so you can physically see the browser window if needed
        args: [
            '--no-sandbox', 
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--no-zygote',
            '--disable-gpu',
            '--log-level=3' // Less Chromium noise
        ],
        timeout: 120000 // 2 minutes timeout for heavy accounts
    }
});

// Target Group Name
const TARGET_GROUP_NAME = "负债🏠35📆";

// Reminder Message Content
const REMINDER_MESSAGE = `
🔔 *【月底结账还钱提醒】* 🔔

大家好！又到了每个月最后一天结账的时候了！💸
请大家核对一下本月的账单，并尽快完成转账。

📌 *转账说明:*
1. 请转账至指定的公账/收款人账户。
2. 转账时请备注你的名字。
3. 转账完成后，请在群里发个截图或说一声“已转”，方便核对。

感谢大家的配合！祝大家新的一月顺顺利利！💪
`;

// Generate QR Code for authentication
client.on('qr', (qr) => {
    console.log('请使用 WhatsApp 扫描下方二维码登录:');
    qrcode.generate(qr, { small: true });
});

// Added 'authenticated' event to know when scan is successful
client.on('authenticated', () => {
    console.log('🔄 扫码成功！正在进行身份验证，请稍候...');
});

client.on('loading_screen', (percent, message) => {
    console.log(`⏳ 正在加载 WhatsApp... ${percent}% - ${message}`);
});

// Added 'auth_failure' event to catch authentication issues
client.on('auth_failure', msg => {
    console.error('❌ 身份验证失败！原因:', msg);
});

// Added state change listener for deep debugging
client.on('change_state', state => {
    console.log(`[DEBUG] WhatsApp State Changed: ${state}`);
});

// Client is ready
client.on('ready', () => {
    console.log('✅ WhatsApp Bot 已成功登录并准备就绪！');
    
    // Set up the cron job once the client is ready
    setupCronJob();
});

// Handle disconnects and auto-reconnect
client.on('disconnected', (reason) => {
    console.log('❌ WhatsApp Bot 已断开连接！原因:', reason);
    console.log('正在尝试重新连接...');
    client.initialize(); // Attempt to reconnect
});

// Setup the cron job for the last day of the month at 8:00 PM (20:00)
function setupCronJob() {
    // Cron expression: 0 20 28-31 * *
    // This runs at 20:00 on days 28-31 of every month.
    // Inside the job, we check if tomorrow is the 1st of the next month.
    console.log('🕒 定时任务已设置：每月最后一天晚上 8:00 执行。');
    
    cron.schedule('0 20 28-31 * *', async () => {
        const today = new Date();
        const tomorrow = new Date(today);
        tomorrow.setDate(tomorrow.getDate() + 1);
        
        // If tomorrow's date is 1, then today is the last day of the month
        if (tomorrow.getDate() === 1) {
            console.log(`[${new Date().toLocaleString()}] 触发提醒任务！正在寻找群组...`);
            await sendReminderToGroup();
        } else {
            console.log(`[${new Date().toLocaleString()}] 今天不是本月最后一天，跳过执行。`);
        }
    });
}

// Function to find the group and send the message
async function sendReminderToGroup() {
    try {
        const chats = await client.getChats();
        // Find the group chat by name
        const groupChat = chats.find(chat => chat.isGroup && chat.name === TARGET_GROUP_NAME);

        if (groupChat) {
            await groupChat.sendMessage(REMINDER_MESSAGE);
            console.log(`✅ 成功发送提醒消息到群组: ${TARGET_GROUP_NAME}`);
        } else {
            console.log(`⚠️ 未找到名为 "${TARGET_GROUP_NAME}" 的群组。请确保机器人已加入该群组并且名字完全匹配。`);
            
            // Log available groups to help with debugging
            console.log("当前机器人所在的群组列表:");
            const groupNames = chats.filter(c => c.isGroup).map(c => c.name);
            console.log(groupNames);
        }
    } catch (error) {
        console.error('❌ 发送消息时发生错误:', error);
    }
}

// Test function: Uncomment this and run the script if you want to test the message immediately
// client.on('ready', async () => {
//     console.log('--- 运行测试发送 ---');
//     await sendReminderToGroup();
// });

// Initialize the client
client.initialize();
