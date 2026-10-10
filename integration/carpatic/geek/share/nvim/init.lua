-- carpatic-starter v1 -- a small, fast Neovim setup from Carpatic OS. No plugins, nothing to download.
-- Yours to change: this file is copied once and never overwritten. Press <Space>? inside Neovim for the key list.
-- Credit: ideas from Neovim's own defaults and the kickstart.nvim project (MIT), rewritten without plugins.

vim.g.mapleader = " "
vim.g.maplocalleader = " "
local o, map = vim.opt, vim.keymap.set

-- Look and feel -------------------------------------------------------------------------------------------------------
o.number, o.relativenumber, o.cursorline, o.signcolumn = true, true, true, "yes"
o.termguicolors, o.scrolloff, o.sidescrolloff, o.wrap = true, 8, 8, false
o.splitright, o.splitbelow, o.showmode = true, true, false
o.list, o.listchars = true, { tab = "» ", trail = "·", nbsp = "␣" }
o.fillchars = { eob = " " }
pcall(vim.cmd.colorscheme, "carpatic")         -- generated from your Carpatic theme (carpatic dev nvim-theme)

-- Editing -------------------------------------------------------------------------------------------------------------
o.expandtab, o.shiftwidth, o.tabstop, o.smartindent = true, 2, 2, true
o.ignorecase, o.smartcase, o.incsearch, o.hlsearch = true, true, true, true
o.undofile, o.updatetime, o.timeoutlen, o.mouse = true, 250, 400, "a"
o.completeopt = { "menu", "menuone", "noselect" }
if vim.fn.executable("xclip") == 1 or vim.fn.executable("wl-copy") == 1 then o.clipboard = "unnamedplus" end
if vim.fn.executable("rg") == 1 then o.grepprg, o.grepformat = "rg --vimgrep --smart-case", "%f:%l:%c:%m" end

-- Keys ------------------------------------------------------------------------------------------------------------------
map("n", "<Esc>", "<cmd>nohlsearch<cr>")
map("n", "<leader>w", "<cmd>write<cr>", { desc = "Save" })
map("n", "<leader>q", "<cmd>quit<cr>", { desc = "Quit" })
map("n", "<leader>e", "<cmd>Lexplore 30<cr>", { desc = "File tree" })
map("n", "<leader>b", function()
  local items = vim.tbl_filter(function(b) return vim.bo[b].buflisted and vim.api.nvim_buf_get_name(b) ~= "" end, vim.api.nvim_list_bufs())
  vim.ui.select(items, { prompt = "Buffer", format_item = function(b) return vim.fn.fnamemodify(vim.api.nvim_buf_get_name(b), ":~:.") end },
    function(b) if b then vim.cmd.buffer(b) end end)
end, { desc = "Buffers" })
-- find files with fd or rg, search text with rg (results in the quickfix list)
map("n", "<leader>f", function()
  local cmd = vim.fn.executable("fd") == 1 and "fd --type f --hidden --exclude .git" or "rg --files --hidden -g '!.git'"
  local files = vim.fn.systemlist(cmd)
  vim.ui.select(files, { prompt = "Open file" }, function(f) if f then vim.cmd.edit(vim.fn.fnameescape(f)) end end)
end, { desc = "Find file" })
map("n", "<leader>/", function()
  vim.ui.input({ prompt = "Search text: " }, function(t) if t and t ~= "" then vim.cmd("silent grep! " .. vim.fn.shellescape(t)) vim.cmd("copen") end end)
end, { desc = "Search in files" })
for _, k in ipairs({ "h", "j", "k", "l" }) do map("n", "<C-" .. k .. ">", "<C-w>" .. k) end
map("v", "J", ":m '>+1<cr>gv=gv"); map("v", "K", ":m '<-2<cr>gv=gv")
map("v", "<", "<gv"); map("v", ">", ">gv")
map("n", "[d", function() vim.diagnostic.jump({ count = -1 }) end, { desc = "Previous problem" })
map("n", "]d", function() vim.diagnostic.jump({ count = 1 }) end, { desc = "Next problem" })
map("n", "<leader>d", vim.diagnostic.open_float, { desc = "Show problem" })
map("n", "<leader>?", function()
  local lines = {}
  for _, m in ipairs(vim.api.nvim_get_keymap("n")) do
    if m.desc and m.lhs:match("^ ") then lines[#lines + 1] = ("%-12s %s"):format(m.lhs:gsub("^ ", "<Space>"), m.desc) end
  end
  table.sort(lines); vim.notify(table.concat(lines, "\n"), vim.log.levels.INFO, { title = "Keys" })
end, { desc = "Show these keys" })

-- Language servers: switched on for whichever of these you have installed (carpatic install dev go, rust, ...) --------
local servers = {
  gopls = { cmd = { "gopls" }, filetypes = { "go", "gomod" }, root = { "go.mod", ".git" } },
  rust_analyzer = { cmd = { "rust-analyzer" }, filetypes = { "rust" }, root = { "Cargo.toml", ".git" } },
  lua_ls = { cmd = { "lua-language-server" }, filetypes = { "lua" }, root = { ".luarc.json", ".git" } },
  clangd = { cmd = { "clangd" }, filetypes = { "c", "cpp" }, root = { "compile_commands.json", ".git" } },
  pylsp = { cmd = { "pylsp" }, filetypes = { "python" }, root = { "pyproject.toml", ".git" } },
  ts_ls = { cmd = { "typescript-language-server", "--stdio" }, filetypes = { "javascript", "typescript" }, root = { "package.json", ".git" } },
}
if vim.lsp.config and vim.lsp.enable then
  for name, s in pairs(servers) do
    if vim.fn.executable(s.cmd[1]) == 1 then
      vim.lsp.config(name, { cmd = s.cmd, filetypes = s.filetypes, root_markers = s.root })
      vim.lsp.enable(name)
    end
  end
end
vim.api.nvim_create_autocmd("LspAttach", { callback = function(ev)
  local b = { buffer = ev.buf }
  map("n", "gd", vim.lsp.buf.definition, vim.tbl_extend("force", b, { desc = "Go to definition" }))
  map("n", "gr", vim.lsp.buf.references, vim.tbl_extend("force", b, { desc = "References" }))
  map("n", "K", vim.lsp.buf.hover, b)
  map("n", "<leader>r", vim.lsp.buf.rename, vim.tbl_extend("force", b, { desc = "Rename" }))
  map("n", "<leader>a", vim.lsp.buf.code_action, vim.tbl_extend("force", b, { desc = "Code action" }))
  map("n", "<leader>=", function() vim.lsp.buf.format({ async = true }) end, vim.tbl_extend("force", b, { desc = "Format" }))
end })
vim.diagnostic.config({ virtual_text = true, severity_sort = true, float = { border = "rounded" } })

-- Syntax: Neovim ships tree-sitter for these; others fall back to classic syntax --------------------------------------
vim.api.nvim_create_autocmd("FileType", { pattern = { "lua", "c", "vim", "help", "markdown", "query" }, callback = function() pcall(vim.treesitter.start) end })

-- A quiet statusline: mode, file, problems, position ----------------------------------------------------------------
function _G.carpatic_status()
  local d = vim.diagnostic.count(0)
  local e, w = d[vim.diagnostic.severity.ERROR] or 0, d[vim.diagnostic.severity.WARN] or 0
  return table.concat({ " %f %m%r", "%=", (e > 0 and (" E" .. e) or ""), (w > 0 and (" W" .. w) or ""), "  %l:%c  %p%% " })
end
o.statusline = "%!v:lua.carpatic_status()"

-- Remember where you were; highlight what you yank ---------------------------------------
vim.api.nvim_create_autocmd("BufReadPost", { callback = function()
  local m = vim.api.nvim_buf_get_mark(0, '"')
  if m[1] > 0 and m[1] <= vim.api.nvim_buf_line_count(0) then pcall(vim.api.nvim_win_set_cursor, 0, m) end
end })
vim.api.nvim_create_autocmd("TextYankPost", { callback = function() vim.highlight.on_yank({ timeout = 150 }) end })
