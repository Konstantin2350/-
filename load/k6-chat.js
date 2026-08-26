import http from "k6/http";
import { check, sleep } from "k6";

const target = Number(__ENV.VUS || 100);

export const options = {
  stages: [
    { duration: "30s", target },
    { duration: __ENV.HOLD || "2m", target },
    { duration: "30s", target: 0 },
  ],
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<1500"],
  },
};

const baseUrl = __ENV.BASE_URL || "http://localhost:8787";
const headers = {
  "Content-Type": "application/json",
  ...( __ENV.API_KEY ? { "x-api-key": __ENV.API_KEY } : {} ),
};

export default function () {
  const response = http.post(
    `${baseUrl}/v1/chat/messages`,
    JSON.stringify({
      session_id: `load-${__VU}`,
      user_id: `load-user-${__VU}`,
      channel: "api",
      message: "Как начать работу с системой?",
    }),
    { headers },
  );
  check(response, {
    "chat returns 200": (result) => result.status === 200,
    "answer is present": (result) => Boolean(result.json("answer")),
  });
  sleep(1);
}
