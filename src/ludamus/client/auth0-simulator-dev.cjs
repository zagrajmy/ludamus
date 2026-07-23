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

app.listen(port, () => {
  console.log(
    `Auth0 simulation server started at https://localhost:${port}\n` +
      `Email: ${email}\nPassword: ${password}\n` +
      "\nPress Ctrl+C to stop the server",
  );
});
