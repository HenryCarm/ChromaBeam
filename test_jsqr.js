const fs = require('fs');
const jsQR = require('/home/henry/node_modules/jsqr/dist/jsQR.js');

const rawBuf = fs.readFileSync('tests/real_phone_screenshot.raw');
const width = 501;
const height = 1024;

const uint8Data = new Uint8ClampedArray(rawBuf);

const code = jsQR(uint8Data, width, height, {
    inversionAttempts: "attemptBoth"
});

console.log("jsQR result:", code ? {
    data: code.data,
    location: code.location
} : "null");
