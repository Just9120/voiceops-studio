import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PlatformSidebar } from "./PlatformSidebar";

describe("PlatformSidebar", () => {
  it("renders the platform brand and all navigation destinations", () => {
    render(<PlatformSidebar page="dashboard" onNavigate={vi.fn()} />);

    expect(screen.getByText("VoiceOps Studio")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "О приложении" })).toHaveAttribute("href", "/about.html");
    expect(
      screen.getByRole("navigation", { name: "Основная навигация" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Обзор" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Подготовка аудио" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Транскрибации" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Настройки" }),
    ).toBeInTheDocument();
  });

  it("marks only the current page as active", () => {
    render(<PlatformSidebar page="projects" onNavigate={vi.fn()} />);

    const current = screen.getByRole("button", { name: "Транскрибации" });
    expect(current).toHaveClass("active");
    expect(current).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Обзор" })).not.toHaveClass(
      "active",
    );
    expect(
      screen.getByRole("button", { name: "Настройки" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("reports the selected destination to the shell", async () => {
    const onNavigate = vi.fn();
    render(<PlatformSidebar page="dashboard" onNavigate={onNavigate} />);

    await userEvent.click(screen.getByRole("button", { name: "Настройки" }));

    expect(onNavigate).toHaveBeenCalledOnce();
    expect(onNavigate).toHaveBeenCalledWith("settings");
  });
});
