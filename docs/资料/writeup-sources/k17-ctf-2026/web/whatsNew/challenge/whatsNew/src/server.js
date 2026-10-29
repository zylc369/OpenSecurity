const express = require("express");
const path = require("path");
const cookieParser = require("cookie-parser");
const categoryRoutes = require("./routes/categoryRoutes");
const adminRoutes = require("./routes/adminRoutes");
const reportRoutes = require("./routes/reportRoutes");

const app = express();
const port = Number(process.env.PORT || 3000);

app.use(cookieParser());
app.use(express.urlencoded({ extended: false, limit: "64kb" }));
app.use(
    "/static",
    express.static(path.join(__dirname, "..", "public", "static")),
);

app.use(categoryRoutes);
app.use(adminRoutes);
app.use(reportRoutes);

app.use((req, res) => {
    res.status(404).type("text/plain").send("not found");
});

app.listen(port, "0.0.0.0", () => {
    console.log(`listening on ${port}`);
});
