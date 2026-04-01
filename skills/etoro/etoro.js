const https = require('https');

async function fetchPortfolio() {
    const apiKey = "sdgdskldFPLGfjHn1421dgnlxdGTbngdflg6290bRjslfihsjhSDsdgGHH25hjf";
    const userKey = "eyJjaSI6IjYwY2FiYjBiLTU1OTctNDQ4NS04ZjYzLTdlOWUwNTZlMGJiOCIsImVhbiI6IlVucmVnaXN0ZXJlZEFwcGxpY2F0aW9uIiwiZWsiOiJEQS1MLllKakIzSDJjZC1RQ0g4eTBMQmtZLWdRR2VNQXl6LkhiVXZUVkVpNUhMb1RNTEtNUEdzZ2ZRSzU0YW8wNTB6SlBjSjZJQVU0YVNobGRGbWpmR3hBZEhwUll3d0hCMUx2M3VwakZKVV8ifQ__";
    const requestId = crypto.randomUUID();

    console.log("Connecting to LIVE eToro API...");
    
    return new Promise((resolve, reject) => {
        const options = {
            hostname: 'public-api.etoro.com',
            port: 443,
            path: '/api/v1/trading/info/portfolio',
            method: 'GET',
            headers: {
                "x-api-key": apiKey,
                "x-user-key": userKey,
                "x-request-id": requestId,
                "Content-Type": "application/json"
            }
        };

        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => data += chunk);
            res.on('end', () => {
                if (res.statusCode >= 200 && res.statusCode < 300) {
                    try {
                        resolve(JSON.parse(data));
                    } catch (e) {
                        reject(new Error("Failed to parse JSON response: " + data));
                    }
                } else {
                    reject(new Error(`Failed with status ${res.statusCode}: ${data}`));
                }
            });
        });

        req.on('error', (e) => reject(e));
        req.end();
    });
}

// Perform live fetch
fetchPortfolio().then(console.log).catch(console.error);
