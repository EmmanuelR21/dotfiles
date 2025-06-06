local gitStatOpen = false

vim.keymap.set("n", "<leader>gs", function()
    if not gitStatOpen then
        vim.cmd('vert Git!')
        gitStatOpen = true
    else
        vim.cmd(":q")
        gitStatOpen = false
    end
end)
