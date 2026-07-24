const { simulation } = require("@simulacrum/auth0-simulator");

const port = Number(process.env.AUTH0_SIMULATOR_PORT ?? 4400);
const email = "default@example.com";
const password = "12345";

const app = simulation({
  initialState: {
    users: [
      {
        id: "local-manager",
        name: "Local Manager",
        email,
        password,
      },
    ],
  },
});

app.listen(port, "127.0.0.1", () => {
  console.log(
    "Auth0 simulation server started at https://auth0.localhost\n" +
      `Email: ${email}\nPassword: ${password}\n` +
      "\nPress Ctrl+C to stop the server",
  );
});
